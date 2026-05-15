# Roadmap Stage 15 Planning: External Artifact Interface Contract

## Metadata

- Roadmap stage: v15
- Source roadmap: `docs/roadmap.md`
- Previous version status:
  `docs/roadmap/stage-14/implementation-plan.md` is complete and records all
  Stage 14 plugin-discovery phases merged. The landed public plugin API
  exports `LOOM_ARTIFACT_STORE_BACKENDS_GROUP =
  "loom.artifact_store_backends"`, generic metadata listing/loading helpers,
  plugin diagnostic summaries, and readiness metadata. Recipes and codecs are
  the only registry-ready groups; artifact-store backends remain listing-only
  in Stage 14 CLI/preflight diagnostics until Stage 15 defines the
  store-owned descriptor/factory, registry, capability, run-context handoff,
  and backend availability contracts.
- Planning artifact status: confirmed and converted to implementation plan
- Current discussion stage: implementation-plan draft created and local
  plan-quality gate passed
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed by recorded checkpoint
  - Design agreement review: confirmed
  - Design safety review: passed with required planning revisions recorded;
    renewed review after Stage 14 revisions passed; latest targeted
    artifact-store backend pass passed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: confirmed
  - Handoff: implementation-plan draft created; local plan-quality gate passed
- Related implementation plan:
  `docs/roadmap/stage-15/implementation-plan.md`
- Related feature docs:
  - `docs/features/remote-stores.md`
  - `docs/features/artifacts.md`
  - `docs/features/io.md`
  - `docs/features/plugins.md`
  - `docs/features/preflight.md`
  - `docs/features/run-catalog.md`
  - `docs/features/reliability.md`
  - `docs/features/testing.md`
- Blockers:
  - None from design-safety review, renewed Stage 14 alignment review, or the
    latest targeted artifact-store backend pass.
  - Stage 14 implementation artifacts and landed plugin APIs were rechecked on
    2026-05-15 for implementation-plan drafting.
  - Stage 12 portable-run exchange source APIs were rechecked on 2026-05-15 for
    implementation-plan drafting.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V15 defines backend-neutral artifact-store APIs, external immutable refs, multi-location artifact semantics, fake handlers, bundle ref semantics, preflight checks, and immutable artifact lookup. | roadmap scope | This is an interface-contract stage, not a payload-transfer or cloud-adapter stage. |
| `docs/roadmap.md` | V15 defers real cloud backend adapters, remote payload export/import, implicit downloads, credential refresh, distributed caches, remote GC, automatic global cache lookup, partial stage reuse, and first-party MLflow/DVC implementations. | scope boundaries | Strong default is fake backends and metadata-only preservation in core. |
| `docs/roadmap.md` v16 | V16 owns explicit payload materialization, publish/upload/download paths, and at most one optional backend family if selected later. | future boundary | Stage 15 should define operation records and unsupported behavior without implementing transfer paths. |
| `docs/roadmap.md` v14 and `docs/roadmap/stage-14/implementation-plan.md` | Stage 14 owns explicit plugin discovery and is complete. Store backend hooks in Stage 15 must be compatible with plugin loading, but Stage 14 does not define Stage 15 store semantics. | prerequisite and dependency alignment | Stage 14 landed the backend-oriented group spelling `loom.artifact_store_backends`; recipes/codecs are registry-ready and artifact-store backends are listing-only until Stage 15 defines their supplied-registry adapter contract. |
| `docs/features/remote-stores.md` | Remote stores preserve the `ArtifactStore` protocol, avoid hard SDK dependencies, declare capabilities, redact credentials, document atomicity and consistency, use manifest-last commit where needed, and keep tests fake-backend-first. | remote-store contract | Strongest source for capability, credential, consistency, staging, cache, preflight, and plugin boundaries. |
| `docs/features/artifacts.md` | `ArtifactRef` is lightweight immutable metadata; local store supports `save`, `register`, `load`, `exists`, and checksum validation; remote stores should not require changing the `ArtifactRef` shape. | artifact contract | Current code already has a run-scoped `ArtifactStore` protocol and local implementation. |
| `src/loom/artifacts.py` | `ArtifactRef` currently allows known fields only: artifact id, URI, type, codec, schema version, checksum, fingerprint, producer stage, timestamp, and plain metadata. | compatibility risk | New multi-location or external-ref fields may need metadata conventions, wrapper records, or a versioned schema change. |
| `src/loom/pipeline/stores/artifact_store.py` | `ArtifactStore` protocol is local/run-oriented and exposes `save`, `register`, `load`, `exists`, `verify_checksum`, and `validate`. | current API surface | Stage 15 likely adds adjacent store config/ref/capability/operation records rather than replacing this protocol outright. |
| `src/loom/pipeline/stores/local_artifacts.py` | `LocalArtifactStore` accepts only local/file URIs, can explicitly allow external local paths, computes checksums for files, and rejects unsupported URI schemes. | local reference behavior | Useful as a baseline for fake remote behavior and for preserving local store compatibility. |
| `src/loom/pipeline/stores/capabilities.py` | Authority backend capability records already exist for lifecycle stores, including artifact-fact and materialization-ref capabilities. | capability vocabulary | Artifact-store capabilities should not be confused with authority capabilities, but can reuse style and plain-data serialization patterns. |
| `docs/features/run-catalog.md` | Catalogs are derived from run-store metadata and should not assume all artifact payloads are local files; export may use metadata-only mode for future remote stores. | catalog and bundle semantics | Stage 15 should define metadata preservation for external/remote refs without claiming payload availability. |
| `docs/roadmap/stage-12/planning.md`, `docs/roadmap/stage-12/implementation-plan.md`, and `src/loom/runs` | Bundle manifests, portable export/import records, importer/exporter protocols, and result envelopes use strict plain records with `extensions` fields. External/remote refs are preserved as metadata and backend-specific semantics are deferred to Stage 15/16. | adjacent artifact exchange | Stage 15 must give those extension fields a stable external-artifact summary contract without requiring downloads. |
| User clarification on Stage 12 | The user expects Stage 12 to be reworked after Stage 15 clarifies generic external artifact interfaces. | adjacent artifact exchange | Stage 15 should define reusable artifact-reference and adapter semantics that Stage 12 portable-run exchange can adopt instead of preserving opaque refs forever. |
| `docs/features/preflight.md` | Existing preflight groups include artifact checks; plugin checks and remote artifact credential probing are deferred or opt-in because they can be environment-specific or slow. | diagnostics surface | Stage 15 should add stable check IDs and cheap/default versus opt-in network checks. |
| `src/loom/diagnostics/models.py` and `src/loom/diagnostics/preflight.py` | Current stable artifact preflight is `artifact_store.available`; Stage 14 added optional plugin checks `plugins.metadata` and `plugins.load` with explicit selectors and listing-only future-group handling. No remote artifact-store backend availability checks exist yet. | current diagnostics code | New backend checks must fit the existing result model, stay distinct from plugin metadata/load checks, and avoid writing final run state. |
| `docs/features/plugins.md`, `src/loom/plugins`, and Stage 14 tests | Plugin discovery is explicit and opt-in. Landed Stage 14 exports `LOOM_ARTIFACT_STORE_BACKENDS_GROUP`, `PluginRecord`, `list_entry_points`, `load_entry_points`, plugin diagnostic/readiness summaries, and `LOADABLE_PLUGIN_GROUPS == (loom.recipes, loom.codecs)`. Artifact-store backends are listing-only in CLI/preflight diagnostics; no `load_artifact_store_backend_entry_points` exists. | plugin compatibility | Stage 15 should define the store-owned backend descriptor/factory/config/capability/registry target shape and, if it lands a plugin adapter, keep it explicit and supplied-registry-based. Stage 14 metadata or import checks must not become backend availability or run-readiness checks. |
| User clarification on Stage 14 | The user wants Stage 15 aligned with Stage 14. | plugin compatibility | Stage 15 should be explicit about the plugin-loadable adapter object shape while still keeping plugin discovery itself in Stage 14. |
| `docs/features/io.md` | URI parsing is centralized, remote schemes are not converted to paths, and I/O codecs do not own artifact-store layout or run-store state. | URI and source boundary | Stage 15 should keep URI/config validation backend-neutral and avoid making I/O a remote store layer. |
| `docs/structure.md` and `docs/GLOSSARY.md` | Keep `loom` domain-neutral; distinguish `ArtifactRef`, `ArtifactAddress`, run store, artifact store, authority, run catalog, status, planner action, checksum, and fingerprint. | vocabulary and architecture | Stage 15 must not introduce domain cache semantics or external service assumptions into core. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, `docs/roadmap.md` v15/v16/v14, module coverage table | Workflow requires a source-backed briefing, then user clarification before capability triage. Roadmap makes v15 an interface-contract stage and v16 the payload-materialization stage. | None for startup. |
| Feature docs | `remote-stores.md`, targeted `artifacts.md`, `run-catalog.md`, `preflight.md`, `plugins.md`, `io.md`, `reliability.md`, `testing.md`, `structure.md`, `GLOSSARY.md` | Feature docs support fake-backend tests, metadata-only refs, redaction, capabilities, manifest-last commit semantics, plugin backend model, conservative staging/cache cleanup, import-boundary tests, and no hard remote dependencies. | None for design-safety review. |
| Source and tests | `src/loom/artifacts.py`, `src/loom/pipeline/stores/artifact_store.py`, `src/loom/pipeline/stores/local_artifacts.py`, `src/loom/pipeline/stores/capabilities.py`, `src/loom/diagnostics/*`, `src/loom/plugins/*`, `src/loom/runs/*`, and targeted plugin/run-exchange tests | Current `ArtifactRef` is strict and compact; local artifact store is file-only; authority capabilities exist separately; preflight has only a local artifact-store availability check; Stage 14 plugin code keeps artifact-store backends listing-only; Stage 12 run exchange has extension fields ready to consume Stage 15 summaries. | None for implementation-plan drafting. Phase planners must still recheck current source before code changes. |
| Prior or adjacent plans | Stage 12 planning/implementation plan, Stage 13 planning, Stage 14 implementation plan, renewed plugin-structure revisions, and targeted artifact-store backend addendum | Stage 12 has portable-run exchange records and extension fields; Stage 13 expects external refs to remain ordinary artifact metadata; Stage 14 completed plugin discovery and explicitly avoids defining Stage 15 artifact-store backend semantics. | Stage 15 should supply the missing artifact-store backend descriptor/factory, registry, contract/API version, and backend check contract rather than depending on a raw plugin object shape or current local-root `ArtifactStoreFactory`. |

## Roadmap Extraction

Baseline roadmap outcome:

- Loom has a backend-neutral external/remote artifact-store interface contract
  with capability records, config/ref value objects, handler registration
  boundaries, operation result/error models, redaction helpers, and fake
  backends for tests.
- Artifact metadata can distinguish managed run artifacts, external immutable
  inputs, and published immutable outputs without requiring local symlinks or
  payload availability.
- Run catalogs and bundle manifests can preserve external/remote artifact refs
  as metadata-only records with redacted URI, store kind, identity,
  checksum/fingerprint facts, immutable reuse key, size when known, and
  capability hints.
- Preflight can report backend plugin availability, cheap URI/config checks,
  selected read/write capabilities, and unsupported operations without
  performing expensive downloads by default.
- Explicit immutable-artifact lookup can answer whether a compatible published
  immutable artifact exists for a project-supplied key and validation policy,
  but cross-run cache reuse does not become automatic planner behavior.

Prerequisites:

- Stable `ArtifactRef` and local `ArtifactStore` semantics.
- Stage 12 bundle/export manifest fields that can preserve opaque external refs.
- Stage 14 plugin discovery group names, generic entry point records, explicit
  loading helpers, and listing-only readiness for artifact-store backends.
- Stage 12 portable-run exchange and bundle manifests are expected to be
  revisited after Stage 15 defines stable external artifact semantics.
- Existing preflight result model and CLI formatting.
- Existing URI parsing and redaction helpers, with any new helpers kept
  backend-neutral.

Primary feature docs:

- `remote-stores.md`
- `artifacts.md`
- `io.md`
- `plugins.md`
- `preflight.md`
- `run-catalog.md`
- `reliability.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Real S3, GCS, Azure, MLflow, DVC, HTTP, or other concrete backend adapters.
- Remote payload export/import, implicit downloads, publish/upload/download
  flows, and broad materialization operations.
- Credential refresh and storage, distributed caches, remote garbage collection,
  signed manifests, cross-region replication, remote run catalog services, and
  automatic global cache lookup.
- Domain-specific cache keys, checkpoint continuation, partial stage reuse, and
  project-specific artifact schemas in core.

Future-roadmap touchpoints:

- V16 consumes the Stage 15 contract for explicit materialization, publish,
  upload, and download operations.
- V17/V18 container executors may need artifact-store capability checks and
  local staging/cache records when payloads must cross container or HPC
  boundaries.
- V19 reliability policies may add retry/timeout/event records around remote
  operations and staging cleanup.
- V20 cleanup and retention consumes owner/retention hints, delete capability,
  cache policy, and authoritative-versus-derived artifact facts.
- External systems such as MLflow, DVC, W&B, or cloud stores should remain
  optional adapters constrained by this generic contract.
- MLflow should be used as a compatibility example and design pressure test,
  not as a first-party implementation in Stage 15.

Compatibility obligations:

- Core installs must not gain cloud SDK or tracking-system dependencies.
- Existing local `ArtifactStore`, `ArtifactRef`, run-store artifact indexes,
  CLI artifact inspection, and tests must keep working.
- Metadata-only workflows must not require credentials or network access.
- Redacted URI and credential-context records must be safe for persisted run
  metadata and PR/debug output.
- Capability checks must be explicit and conservative; unknown support cannot
  silently become supported.
- Fake backend tests must exercise the durable contract without network,
  containers, cloud accounts, or external services.

## Stage Briefing

What this stage is:

- V15 is Loom's external artifact interface contract stage. It defines how Loom
  describes, validates, records, and reasons about artifact locations that are
  not simply local run-directory payloads. The stage should produce generic
  records and handler boundaries for external immutable inputs, published
  immutable outputs, remote-like artifact stores, store capabilities, plugin
  backend registration, preflight diagnostics, and metadata-only bundle/catalog
  preservation.

Why this stage exists:

- Earlier stages intentionally kept artifact behavior local, inspectable, and
  metadata-first. That avoided premature cloud dependencies, but it leaves a
  gap for reusable project-declared artifacts, shared read-only references,
  remote object stores, and external tracking systems.
- Stage 12 deliberately preserves external refs as opaque bundle metadata until
  this stage defines stable semantics. Stage 14 has landed explicit plugin
  discovery and keeps artifact-store backend entries listing-only, so backend
  plugins need this stage to define what a backend handler actually provides.
  Stage 16 then uses the contract to add explicit payload movement only after
  the durable metadata shape is stable.

Impacted or linked work:

- `loom.artifacts` owns `ArtifactRef` and `ArtifactAddress`. Stage 15 must
  decide whether multi-location and external/published identity live in new
  adjacent records, typed metadata conventions, or a compatible `ArtifactRef`
  schema expansion.
- `loom.pipeline.stores.artifact_store` owns the current `ArtifactStore`
  protocol. Stage 15 likely adds store config refs, backend handlers,
  capabilities, operation results, and registry/factory boundaries without
  breaking the current local store.
- `loom.pipeline.stores.local_artifacts` remains the reference local
  implementation and should not become a remote abstraction by accident.
- `loom.diagnostics.preflight` needs new artifact/backend checks, probably with
  cheap default checks and explicit opt-in expensive/network checks.
- `loom.runs` and bundle/export code need metadata-only ref preservation
  semantics and compatibility records, not default payload downloads.
- `loom.plugins` exposes the landed Stage 14 discovery/readiness primitives;
  Stage 15 needs a stable artifact-store backend entry point target shape and
  supplied-registry adapter boundary before backend entries can be loaded
  usefully.
- `loom.io.uris` can provide URI parsing/redaction helpers, but I/O should not
  become the artifact-store or remote-backend layer.

Likely public surfaces and durable artifacts:

- `ArtifactStoreConfig` or similar backend-neutral config/ref records.
- `ArtifactStoreCapabilities` with readable, writable, listable,
  atomic-commit, checksum-verification, and delete support, plus consistency
  and commit-policy hints if design agreement confirms them.
- Backend handler or factory protocols for resolving config into run-scoped or
  reference-scoped artifact-store behavior.
- External input artifact declaration/registration records with URI, type,
  schema version, checksum, semantic fingerprint, immutability assertion, and
  project metadata.
- Published immutable artifact records with producer provenance,
  deterministic reuse key, checksum/fingerprint evidence, owner/retention
  hints, and validation policy.
- Multi-location or artifact-location records that can distinguish managed,
  external immutable, published immutable, cache, staging, and materialized
  locations without making cache authoritative.
- Operation result/error records for metadata checks, lookup, validation,
  preflight, unsupported payload movement, and manifest-last commit
  expectations.
- Fake external/remote store handlers and contract tests.
- Run-catalog and bundle manifest fields for metadata-only preservation.

Structure rationale:

- The interface should live near artifact-store ownership, probably under
  `loom.pipeline.stores` for store handlers/capabilities plus `loom.artifacts`
  for ref/value-object types that are safe to expose broadly. CLI and preflight
  should wrap these APIs instead of owning semantics.
- Plugin discovery should remain an outer coordination layer. Store backends
  can be plugin-loaded after this stage defines a handler/factory contract, but
  discovery itself should not decide artifact semantics.
- The first implementation should be fake-backend-first because the durable
  behavior is capability, metadata, and diagnostic shape. Real backends would
  add dependencies and operational assumptions before the generic contract is
  reviewable.
- MLflow is useful as a worked example because it exercises external tracking,
  artifact URI indirection, run identity, credentials, and metadata-only
  inspection. The core contract should remain arbitrary-adapter shaped so the
  same interfaces also fit DVC, object stores, HTTP read-only refs, local
  published directories, and future project-specific stores.

Visible assumptions, risks, and constraints:

- The current `ArtifactRef.from_dict` rejects unknown top-level fields. Any
  schema expansion needs deliberate compatibility handling.
- `ArtifactRef.metadata` can carry plain extension facts, but putting core
  semantics only in untyped metadata may weaken validation and make bundle or
  catalog behavior ambiguous.
- "Immutable" must mean a project-declared contract with validation evidence,
  not a universal truth about an external URI.
- Explicit immutable lookup should not become automatic global cache reuse.
  Planner adoption should require a configured lookup result and type/schema
  plus checksum or fingerprint validation.
- Credential checks and remote existence probes can be slow, unavailable, or
  environment-specific. Defaults should avoid network-heavy behavior unless the
  user selects it.
- Stage 14 implementation is complete, but it intentionally does not provide an
  artifact-store backend loader. Stage 15 should preserve plugin freedom, use
  the landed `loom.artifact_store_backends` group spelling in examples and
  planning, and keep Stage 14 CLI/preflight metadata checks distinct from
  Stage 15 backend availability and run-readiness checks.

User clarification questions and resolved answers:

- Roadmap framing confirmed: Stage 15 should focus on generic and arbitrary
  aspects, interfaces, and adapters.
- Stage 15 should consider an example such as MLflow, but the example is a
  compatibility/design pressure test rather than a concrete adapter
  implementation.
- Stage 15 should align with landed Stage 14 plugin-discovery APIs by defining
  the artifact-store backend handler/factory contract that explicit plugin
  adapters can load into a supplied store registry.
- Renewed Stage 14 alignment confirmed that the contract should include a
  stable handler/factory/config/capability/registry shape for
  `loom.artifact_store_backends`, while avoiding a universal plugin object
  protocol or raw `ArtifactStore` instance loading.
- The latest targeted Stage 14 artifact-store backend addendum further
  clarifies that Stage 14 has no backend loader, no store registry mutation, no
  raw `ArtifactStore` or local-root factory plugin target, and no run-readiness
  claim. Stage 15 should therefore define the first loadable artifact-store
  backend descriptor/factory contract, including contract/API versioning,
  backend kind/key policy, explicit config and run-context handoff, and
  backend availability diagnostics separate from Stage 14 metadata checks.
- Stage 12 is expected to be reworked once Stage 15 makes external artifact
  reference semantics concrete.
- Default preflight should use cheap checks by default and fail closed when a
  selected remote write backend lacks required capabilities. Network,
  credential, and payload probes remain opt-in.
- Examples should include MLflow plus one contrasting object-store-style
  adapter example so design review covers both tracking-system indirection and
  URI/capability/consistency semantics.
- Stage 12 portable-run exchange and bundle/export/import rework is in scope
  for Stage 15 phase shaping, not only a future note.
- `ArtifactRef` strategy is confirmed at planning level: keep broad external,
  published, and multi-location semantics in adjacent typed records by default,
  and permit a minimal versioned `ArtifactRef` revision only if design review
  shows concrete validation, compatibility, or ambiguity-reduction guarantees
  that metadata summaries cannot provide.

## User Intent

Target audience:

- Core Loom API authors, plugin/adapter authors, and downstream project owners
  who need to reference or publish artifacts outside one local run directory
  without binding Loom core to a specific remote service.

User-visible outcome:

- Users and adapter authors can describe external artifact refs, published
  immutable outputs, store capabilities, and unsupported operations through a
  generic contract. They can inspect/preflight these refs and preserve them
  through catalog/bundle metadata without needing a real backend dependency.

Success criteria:

- The interface remains backend-neutral and arbitrary-adapter friendly.
- MLflow-like behavior can be explained through the contract without adding an
  MLflow dependency or special-case API.
- Stage 14 has a clear artifact-store backend target object shape available for
  explicit future/plugin-adapter loading once Stage 15 defines the store-owned
  registry contract.
- Stage 12 has a clear rework path from opaque external-ref extension fields to
  stable metadata records.

Non-goals:

- No first-party MLflow, DVC, cloud, HTTP, or tracking-system backend
  implementation.
- No payload upload/download/materialization default path.
- No automatic global cache lookup, partial stage reuse, or domain-specific
  artifact semantics in core.

Constraints:

- Keep contracts generic, typed, and plain-data serializable.
- Preserve local artifact-store compatibility and import-light core behavior.
- Treat authored config as trusted project code while keeping persisted
  metadata redacted and shareable.
- Keep Stage 15 compatible with Stage 14 plugin discovery and future Stage 12
  portable-run exchange rework.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- Stage 15 is confirmed as a generic external artifact interface and adapter
  contract stage. It should focus on arbitrary, reusable interfaces rather than
  concrete backends. MLflow is an example/design pressure test only. Stage 14
  alignment and later Stage 12 rework are explicit planning inputs.

Intent discovery locked decisions:

- The primary audience includes core Loom maintainers and adapter/plugin
  authors. The visible outcome should be adapter-ready external artifact
  metadata, capability, preflight, and preservation semantics rather than a
  concrete service integration.

Capability triage and candidate-functional-requirement readback:

- Candidate requirements now include backend-neutral config/ref/capability
  records, plugin-loadable handler/factory contracts, external immutable input
  registration, published immutable output lookup, multi-location metadata,
  preflight checks, catalog/bundle preservation, MLflow-like compatibility
  examples, and a Stage 12 portable-run exchange rework path. The
  `ArtifactRef` compatibility strategy is confirmed as adjacent typed records
  by default, with a narrow versioned `ArtifactRef` revision allowed only if it
  materially improves validation or persisted guarantees.

Functionality-agreement readback:

- Confirmed. Stage 15 includes backend-neutral artifact-store config/ref and
  capability records; Stage 14-compatible store handler/factory contracts;
  fake external/remote handlers; external immutable input registration;
  published immutable output registration and explicit lookup; multi-location
  artifact metadata; cheap default preflight with fail-closed selected remote
  writes; catalog and bundle metadata preservation; Stage 12 portable-run
  exchange and bundle/export/import metadata rework; and MLflow-like plus
  object-store-style compatibility examples. It excludes real backends and
  payload materialization.

Functionality and behavior confirmation readback:

- Confirmed. Defaults remain metadata-first and fake-backend-first. Remote or
  external refs are preserved as stable metadata without credential or payload
  access by default. Selected remote write backends must declare required
  capabilities or fail preflight. Network, credential, and payload probes are
  opt-in. Caches and staging records are derived and never authoritative.

Design-agreement follow-up:

- Confirmed. Design agreement keeps broad artifact semantics in adjacent typed
  records by default; locates broadly reusable artifact identity records in
  `loom.artifacts` and store handler/capability/registry contracts under
  `loom.pipeline.stores`; keeps Stage 14 responsible for plugin discovery while
  Stage 15 defines the plugin-loadable target object shape; keeps Stage 12
  exchange rework under `loom.runs`/portable-run exchange; records a
  capability-aware fake-backend-first design; and carries no unresolved
  high-impact design questions into design-safety review.

Design-safety review follow-up:

- Completed. The safety pass found no blocker requiring user discussion and
  upheld the confirmed functionality, behavior, and design baseline with
  planning revisions. The review updated the Stage 14 dependency to the
  confirmed `loom.artifact_store_backends` group spelling, sharpened the Stage
  12 rework dependency against current portable-run exchange extension fields,
  required handler contracts to distinguish metadata validation from later
  payload materialization operations, and reclassified the MLflow-like plus
  object-store examples as a recorded recommendation rather than an
  auto-approved decision.
- Renewed after Stage 14 planning revisions. The addendum confirmed the revised
  Stage 14 plugin structure is compatible with Stage 15 if Stage 15 defines the
  backend handler/factory/config/capability/registry shape that
  `loom.artifact_store_backends` adapters register into, keeps programmatic
  registry use first-class, and does not broaden the pattern into a universal
  plugin object protocol. No blocker or `needs discussion` item remains from
  the renewed review.
- Latest targeted pass after the Stage 14 artifact-store backend addendum:
  completed locally. The pass confirmed the new Stage 14 wording strengthens
  the Stage 15 boundary. Stage 15 must own the descriptor/factory, supplied
  registry, contract/API version, capability model, URI/config validation,
  redaction, operation-result, preflight, and run-context construction
  contracts before any backend loader can be meaningful. Stage 14 metadata
  checks and import-only diagnostics are not backend availability or
  run-readiness checks. No blocker or `needs discussion` item remains from this
  pass.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Generic and arbitrary interfaces/adapters; MLflow as example only; align with Stage 14; expect Stage 12 rework | Treat v15 as metadata/interface contract; defer payload movement and real backends | None for roadmap framing | Capability triage |
| Intent discovery | Core and adapter authors are primary audience; backend-neutral user-visible contract is the outcome | Keep MLflow/DVC/cloud out of core dependencies | None for intent discovery | Capability triage |
| Capability triage and candidate functional requirements | Generic records, adapter handlers, Stage 14 loader target, Stage 12 exchange rework, and adjacent-record-first `ArtifactRef` strategy are in scope | Fake-backend-first validation; MLflow plus object-store examples; cheap default preflight with fail-closed selected remote writes | None for capability triage | Functionality agreement review |
| Functionality agreement review | Backend-neutral records, Stage 14-compatible handlers, fake handlers, external immutable refs, published immutable lookup, multi-location metadata, preflight, catalog/bundle preservation, Stage 12 rework, and examples confirmed | Preserve scope as interface/contracts plus Stage 12 metadata rework; no real backend or payload materialization | None for functionality agreement | Behavior confirmation |
| Functionality and behavior confirmation | Metadata-first behavior confirmed; selected remote writes fail closed on missing capabilities; network/credential/payload probes opt-in; caches/staging are non-authoritative | Preserve no-download/no-credential default | None for behavior baseline | Context checkpoint |
| Context compaction/reset checkpoint | Checkpoint recorded in this artifact | Reload this artifact plus source roadmap and related feature docs before design agreement | None | Design agreement review |
| Design agreement review | Adjacent-record-first artifact compatibility, stores-owned backend contracts, Stage 14 loader target shape, capability model, explicit immutable lookup, preflight policy, Stage 12 exchange ownership, and example strategy confirmed | Keep contracts generic, import-light, plain-data serializable, fake-backend-first, and metadata-only by default | None for design agreement | Design safety review |
| Design safety review | Passed with required planning revisions; renewed Stage 14 alignment review passed; latest targeted artifact-store backend pass passed; no blockers or `needs discussion` decisions remain | Use `loom.artifact_store_backends`; define contract-specific descriptor/factory/handler/config/capability/registry shape with contract/API versioning; keep Stage 14 checks metadata-only; keep Stage 12 rework metadata-only; keep handler contracts metadata/check/lookup-oriented until Stage 16 payload materialization | None for design safety | Examples and validation strategy |
| Examples and validation strategy | MLflow-like and object-store-style examples confirmed as pressure tests for the same generic contracts | Fake handlers/backends only; no service SDKs, network, credentials, or payload access in default tests | None | Phase shaping |
| Phase shaping | Six implementation-plan phase candidates confirmed: contracts, backend registry/fakes, registration/lookup, preflight/catalog/bundle preservation, Stage 12 rework, and examples/docs/validation hardening | Keep implementation phases small and do not implement future Stage 16 payload movement | None | Implementation readiness |
| Implementation readiness | Planning artifact has confirmed requirements, design decisions, design-safety evidence, examples/validation, phase shape, and completed Stage 12/14 source/API rechecks | Phase execution planners must still recheck current source before making code changes | None | Handoff |
| Handoff | `docs/roadmap/stage-15/implementation-plan.md` drafted from this planning artifact and locally quality-gated | Do not create phase execution plans until selecting Phase 1 and creating its phase execution plan | None | Phase 1 execution planning |

## Capability Triage

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Backend-neutral artifact-store config/ref records | include, confirmed | Roadmap explicitly requires store config/ref value objects; user asked for generic and arbitrary interfaces. | Design pass owns exact shape. |
| Artifact-store capability model | include, confirmed | Required for preflight, unsupported operations, fake backend tests, and arbitrary adapter behavior. | Design pass owns exact fields. |
| Store registry and handler hooks | include, confirmed | Needed for Stage 14 plugin compatibility and optional future backends. | Define the target contract that explicit plugin adapters can load through the landed Stage 14 generic discovery primitives, without changing Stage 14 metadata-only CLI/preflight semantics. |
| External immutable input artifact registration | include, confirmed | Roadmap explicitly requires authored/preflight registration. | Design pass owns config shape and validation strictness. |
| Published immutable output registration and lookup | include, confirmed | Enables explicit reuse without automatic global cache semantics. | Design pass owns planner integration boundary. |
| Multi-location artifact semantics | include, confirmed | Distinguishes managed, external, published, staging, cache, and materialized locations. | Adjacent typed records are the default compatibility strategy. |
| Run catalog and bundle metadata-only preservation | include, confirmed | Required by Stage 12 and v15 exit criteria. | Must not download payloads by default; Stage 12 rework should adopt these records. |
| Fake external/remote handlers | include, confirmed | Required for default tests without real services. | Fake should cover capability and manifest-last behavior. |
| MLflow compatibility example | include as example, confirmed | User asked to consider an example such as MLflow. | Use for examples and design-safety pressure testing only; no MLflow dependency or adapter implementation. |
| Object-store-style compatibility example | include as example, confirmed | User agreed a contrasting example should accompany MLflow. | Exercise URI/capability/consistency semantics without selecting S3/GCS/Azure as an implementation. |
| Stage 12 portable-run exchange rework | include, confirmed | User said the Stage 12 rework is important and should be included as phase scope. | Scope should update bundle/export/import metadata semantics to consume Stage 15 records without adding payload materialization. |
| Real cloud/MLflow/DVC backend implementations | defer | Roadmap explicitly defers concrete adapters. | Candidate compatibility notes only. |
| Payload materialization, publish, upload, download | defer | V16 owns explicit payload movement. | V15 may define unsupported operation results. |
| Credential refresh/storage management | out of scope | Roadmap explicitly defers; core should avoid secrets in metadata. | Cheap/redacted credential checks may be opt-in preflight. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Confirm v15 is primarily an interface and metadata-contract stage, not a payload-transfer or concrete-backend stage. | Roadmap framing | 1 | Keep Stage 15 contract-only with fake backends; defer real backends and payload movement to V16 or later. | Prevents scope creep and dependency churn. | User confirmed generic interfaces/adapters focus. | confirmed |
| FRQ-2 | Choose the user-visible primary outcome: external immutable inputs, published immutable outputs, remote-store handler readiness, or balanced foundation. | FRQ-1 | 2 | Balanced foundation, with explicit immutable lookup and adapter-ready metadata as the main user-visible behavior. | Phase shape depends on which path gets first-class examples and CLI/API emphasis. | User confirmed generic/arbitrary aspects and interfaces/adapters rather than one concrete backend. | confirmed |
| FRQ-3 | Decide how hard to lean on Stage 14 plugin compatibility after Stage 14 plugin discovery landed. | FRQ-1 | 3 | Define a generic handler/factory contract, use the landed `loom.artifact_store_backends` group spelling, and keep artifact-store backend loading explicit and supplied-registry-based. | Preserves Stage 14's listing-only CLI/preflight boundary while giving Stage 15 a stable adapter target. | User asked to align with Stage 14. | confirmed |
| FRQ-4 | Decide whether `ArtifactRef` should be schema-expanded or whether external/multi-location semantics should live in adjacent records with compatible `ArtifactRef` metadata. | FRQ-1 | 4 | Prefer adjacent typed records plus stable metadata summaries by default, but explicitly evaluate whether a minimal versioned `ArtifactRef` revision improves guarantees enough to justify the persisted compatibility cost. | `ArtifactRef.from_dict` is strict; top-level changes affect persisted compatibility, but a narrow revision could improve validation and make external/published refs less ambiguous. | User agreed: adjacent typed records are the default, with a narrow versioned `ArtifactRef` revision allowed only for concrete guarantee improvements. | confirmed |
| FRQ-5 | Define default preflight strictness for remote/external checks. | FRQ-1, FRQ-2 | 5 | Cheap local/config/plugin/capability checks by default; selected remote write backends fail closed when required capabilities are missing; network/credential/payload probes are opt-in. | Avoids surprising slow checks while keeping explicitly selected remote-write runs honest. | User agreed. | confirmed |
| FRQ-6 | Define the Stage 12 rework target for bundle/export/import and portable-run exchange. | FRQ-1, FRQ-4 | 6 | Include a Stage 15 phase or equivalent scoped work item that updates Stage 12 portable-run exchange and bundle/export/import metadata semantics to adopt Stage 15 external artifact records. | Prevents Stage 12 from hardening an incompatible bundle extension shape. | User explicitly said Stage 12 rework is important and should be included. | confirmed |

## Functional Requirements

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Backend-neutral artifact-store records | none | Define config/ref/capability value objects and serialization. | Remote-like stores need portable metadata and diagnostics. | Core records only; no real backend SDKs. | Users can inspect selected store kind, redacted URI, and capabilities. | Records validate plain data and reject ambiguous/secret-bearing fields. | Store registry and preflight. | Unit tests for validation, redaction, serialization. | confirmed |
| FR-2 | External immutable input registration | FR-1 | Register external refs with URI, type, schema version, checksum/fingerprint, immutability assertion, and metadata. | Shared reference artifacts need durable identity without copying payloads. | Metadata and validation; no download by default. | Config/preflight can surface external inputs as refs. | Store handler validates URI/config and records facts. | Reference artifact support. | Contract tests with fake read-only backend and local external refs. | confirmed |
| FR-3 | Published immutable output registration and lookup | FR-1 | Record project-supplied reuse keys, provenance, evidence, owner/retention hints, and validation policy. | Enables explicit reuse of expensive immutable outputs. | Explicit API; no automatic global cache. | Users can ask whether a compatible immutable artifact exists. | Lookup returns structured compatible/incompatible/unsupported results. | Controlled cross-run reuse. | Unit/contract tests for lookup decisions and planner handoff records. | confirmed |
| FR-4 | Multi-location artifact semantics | FR-1 | Model managed, external, published, staging, cache, and materialized locations. | Catalogs and bundles need to preserve location meaning safely. | Metadata semantics; not transfer operations. | Inspection shows what kind of location each ref uses. | Cache/staging records are derived/non-authoritative. | V16 materialization and V20 cleanup. | Serialization and catalog/bundle tests. | confirmed with adjacent-record-first compatibility strategy |
| FR-5 | Store handler registry and fake backend | FR-1 | Define handler/factory protocol, config/ref handoff, capability reporting, registry behavior, fake backend, and unsupported operations. | Plugin and test compatibility need stable backend shape. | Core fake only; no raw `ArtifactStore` instance plugin contract. | Preflight/check commands can use fake and configured handlers. | Registry resolves by backend kind, reports duplicates/missing handlers, and accepts programmatic registration independent of plugin discovery. | Stage 14 plugin loading and Stage 16 adapters. | Contract tests for fake backend, duplicate/missing handlers, config normalization, and plugin-adapter-ready registration. | confirmed |
| FR-6 | Preflight integration | FR-1, FR-5 | Add artifact-store backend/config/capability/ref checks with stable IDs. | Users need diagnostics before runs depend on external refs. | Default cheap checks; opt-in expensive checks. | `loom preflight` reports missing plugin, invalid URI, unsupported writes, and optional credential/read checks. | Checks avoid writing final run state or downloading payloads by default. | Operational readiness. | Unit/integration tests with fake backend. | confirmed |
| FR-7 | Run catalog and bundle metadata preservation | FR-1, FR-4 | Define manifest/catalog summary fields for external/remote refs. | Stage 12 requires opaque refs to become stable metadata. | Metadata-only by default. | Export/import/inspect preserve refs without credentials. | Bundle/catalog serializers include redacted URI, store kind, identity, checksum/size/capability hints. | Portable metadata exchange. | Bundle/catalog tests with fake remote refs. | confirmed |
| FR-8 | Adapter compatibility examples | FR-1, FR-5 | Document at least one MLflow-like external artifact adapter mapping through the generic contract. | Examples pressure-test arbitrary adapter design without adding dependencies. | Documentation/examples and fake records only. | Users can see how an external tracking system would fit the generic contract. | Example maps MLflow-like tracking URI, artifact URI, run identity, capabilities, and unsupported operations to generic records. | Design-safety review and adapter author guidance. | Docs/example tests if examples are executable; otherwise reviewer checklist. | confirmed |
| FR-9 | Stage 12 exchange rework | FR-1, FR-4, FR-7 | Update Stage 12 portable-run exchange, bundle manifest, export/import/inspect, and unsupported-materialization metadata semantics to adopt Stage 15 external artifact records. | Prevents long-lived opaque extension fields after Stage 15 and keeps exchange artifacts aligned with adapter contracts. | Metadata and contract alignment only; no remote payload materialization. | Bundle/export/import docs and APIs treat external refs as stable metadata rather than opaque extensions. | Portable-run exchange preserves generic external artifact summaries, redacted store refs, capability hints, immutable identity, and unsupported materialization diagnostics. | Bundle/catalog compatibility. | Contract fixtures showing bundle/catalog summaries round-trip external refs, plus no-payload-download assertions. | confirmed |
| FR-10 | Object-store-style compatibility example | FR-1, FR-5 | Document a generic object-store-style adapter mapping through the same contract. | Contrasts with MLflow and pressure-tests URI, consistency, checksum, listing, and delete capabilities. | Documentation/examples and fake records only. | Users can see that the interface is not tracking-system-specific. | Example maps object-store URI, namespace/prefix, eventual consistency, checksum support, and unsupported operations to generic records. | Design-safety review and adapter author guidance. | Docs/example tests if examples are executable; otherwise reviewer checklist. | confirmed |

## Behavior Baseline

Included functionality:

- Backend-neutral external artifact config/ref/capability records.
- Stage 14-compatible artifact-store handler/factory contracts and registry
  behavior.
- Fake external/remote handlers for contract and preflight tests.
- External immutable input artifact registration from authored config or
  preflight resolution.
- Published immutable output registration and explicit lookup by
  project-supplied key and validation evidence.
- Multi-location artifact metadata for managed, external, published, staging,
  cache, and materialized locations.
- Run catalog and bundle metadata preservation for external and remote refs.
- Stage 12 portable-run exchange and bundle/export/import metadata rework to
  adopt Stage 15 records.
- MLflow-like and object-store-style compatibility examples.

User-visible behavior:

- Users and adapter authors can inspect external artifact refs, redacted store
  refs, capability hints, immutable identity, and unsupported operation
  diagnostics as stable metadata.
- Catalog and bundle workflows preserve external refs without credentials or
  payload downloads by default.
- Explicit immutable lookup can report compatible, incompatible, missing, or
  unsupported results without becoming automatic global cache reuse.

Default behavior:

- Metadata-only preservation by default.
- Fake-backend-first validation in core tests.
- Adjacent typed records carry external, published, and multi-location
  semantics by default; a minimal `ArtifactRef` revision is allowed only when
  design review proves it improves concrete guarantees.
- Preflight runs cheap local/config/plugin/capability checks by default.

Failure behavior and diagnostics:

- Missing handlers, duplicate handler keys, invalid store config, invalid URI,
  missing required capabilities, checksum/fingerprint mismatches, unsupported
  operations, and unsafe secret-bearing metadata are structured diagnostics.
- Selected remote write backends fail preflight when required capabilities are
  missing.
- Network, credential, and payload probes are opt-in so environment-specific
  failures do not break metadata-only inspection by default.

Explicit deferrals:

- Real MLflow, DVC, S3, GCS, Azure, HTTP, or tracking-system backends.
- Payload upload, download, publish, import materialization, and implicit
  bundle downloads.
- Credential refresh or credential storage.
- Distributed caches, remote garbage collection, signed manifests, remote run
  catalog services, and cross-region replication.

Out-of-scope behavior:

- Automatic global cache lookup for arbitrary stage outputs.
- Partial stage reuse and domain-specific checkpoint continuation.
- Treating cache or staging locations as authoritative artifact truth.
- Domain-specific artifact schemas, metrics, model registry semantics, or
  external tracking behavior in core.

Context compaction/reset checkpoint:

- Checkpoint status: recorded after functionality and behavior confirmation
- Notes path: `docs/roadmap/stage-15/planning.md`
- Resume instruction: reload this planning artifact, `docs/roadmap.md` v15/v16,
  `docs/roadmap/stage-14/planning.md`, `docs/roadmap/stage-12/planning.md`,
  `docs/roadmap/stage-12/implementation-plan.md`, and related feature docs
  before design agreement.
- Functionality and behavior reopened after checkpoint: no

## Proposed Implementation Shape

Likely modules or packages:

- `loom.artifacts`: broadly reusable artifact identity and location value
  objects that must be safe to reference from stores, run catalog, bundle
  exchange, provenance, and docs without importing backend implementations.
  Candidate additions include artifact location kind, artifact location summary,
  external artifact declaration, published artifact identity, immutable lookup
  request/result, and stable metadata summary helpers.
- `loom.pipeline.stores`: artifact-store backend contracts, capability records,
  handler/factory protocols, backend registry, operation result/error records,
  fake backend handlers, and capability admission helpers. These remain
  artifact-store semantics, not run lifecycle authority semantics.
- `loom.io.uris`: shared URI parsing/redaction helpers only when they stay
  backend-neutral. Backend-specific joining, signing, credential probing, and
  schema validation remain handler responsibilities.
- `loom.diagnostics.preflight`: artifact-store backend/config/capability checks
  over the public store records and handlers. Checks must not write final run
  documents or fetch payloads by default.
- `loom.runs`: Stage 12 portable-run exchange and bundle/export/import metadata
  rework. This layer consumes Stage 15 external artifact summaries and
  unsupported-materialization diagnostics without making stores import
  `loom.runs`.
- `loom.plugins`: Stage 14 remains the discovery/loading coordinator and
  artifact-store backend metadata/readiness namespace. Stage 15 defines the
  artifact-store backend target object shape and supplied-registry adapter
  boundary that explicit plugin loading can use without making CLI/preflight
  metadata checks claim backend availability.

Public API or protocol candidates:

- `ArtifactLocationKind` and `ArtifactLocationSummary`: plain-data location
  meaning for managed, external immutable, published immutable, staging, cache,
  and materialized refs.
- `ExternalArtifactDeclaration`: authored or preflight-resolved external input
  ref facts, including store ref, URI, artifact type, schema version,
  checksum/fingerprint facts, immutability assertion, and project metadata.
- `PublishedArtifactRecord`: producer provenance, deterministic reuse key,
  checksum/fingerprint evidence, owner/retention hints, and validation policy
  for immutable outputs published outside a run artifact root.
- `ArtifactStoreRef` or `ArtifactStoreConfig`: backend-neutral store kind, URI
  or root ref, options summary, and redacted display fields.
- `ArtifactStoreCapabilities`: capability records with read/write/list/delete,
  checksum verification, commit/consistency hints, and support status that can
  distinguish supported, unsupported, and unknown.
- `ArtifactStoreBackendDescriptor` or `ArtifactStoreBackendFactory`:
  plugin-loadable target shape for `loom.artifact_store_backends` after Stage
  15 exists. It declares contract/API version, backend kind/key, supported URI
  schemes, config schema or validator, redaction behavior, capability provider,
  cheap preflight hooks, operation/failure result compatibility, and the
  run-context store-construction handoff. It is not an opened `ArtifactStore`,
  current local-root `ArtifactStoreFactory`, or plugin-owned registry.
- `ArtifactStoreBackendHandler` protocol: store-owned normalized handler shape
  that validates config, redacts refs, reports capabilities, produces cheap
  preflight diagnostics, opens or adapts store operations when supported, and
  returns structured unsupported results for out-of-stage payload operations.
  Plugins may later supply descriptors/factories that normalize into this
  contract, but programmatic registration must work without plugins.
- `ArtifactStoreBackendRegistry`: explicit registry keyed by backend kind with
  deterministic duplicate handling and programmatic registration as the primary
  path; Stage 14 plugin loaders are adapters into this registry, not owners of
  store semantics.
- `ImmutableArtifactLookupRequest` and `ImmutableArtifactLookupResult`:
  explicit lookup contract that returns compatible, incompatible, missing, or
  unsupported without enabling automatic global cache reuse.

Persisted records and schemas:

- External artifact summaries and published artifact records must be
  strict-versioned plain data with explicit unknown-field policy.
- `ArtifactRef` remains stable by default. External, published, and
  multi-location semantics live in adjacent records plus stable metadata
  summaries. A minimal versioned `ArtifactRef` revision is allowed only if
  design-safety review or implementation planning proves it materially improves
  validation or persisted compatibility.
- Bundle and portable-run exchange records from Stage 12 should replace opaque
  external-ref extensions with Stage 15 summaries, redacted store refs,
  capability hints, immutable identity, and unsupported-materialization
  diagnostics.
- Cache and staging records are derived/non-authoritative and must include
  enough cleanup/revisit facts for Stage 16/V19/V20 without pretending payload
  availability is guaranteed.

CLI and preflight surfaces:

- Stage 15 does not require a new command family by default. Existing or future
  artifact/run/bundle/preflight commands should present external artifact facts
  through their owning surfaces.
- Preflight adds stable artifact-store backend/config/capability checks.
  Defaults are cheap: config shape, handler availability, URI parse/redaction,
  required capability presence, and unsupported-operation diagnostics.
- Selected remote write backends fail closed when required capabilities are
  unsupported or unknown. Network, credential, existence, checksum, and payload
  probes remain opt-in.

Import-boundary and dependency notes:

- No cloud, MLflow, DVC, HTTP client, object-store SDK, or tracking-system
  dependency enters core.
- Top-level `loom.artifacts` must not import stores, diagnostics, plugins,
  `loom.runs`, or optional backend packages.
- Store backend contracts may import `loom.artifacts`, `loom.io.uris`, and
  serialization/errors helpers, but must not import CLI, plugin discovery,
  run-bundle internals, or concrete optional backends.
- `loom.plugins` may load backend handlers explicitly, but subsystem registries
  do not discover plugins on import.
- `loom.runs` consumes artifact summaries for exchange/bundle behavior; stores
  do not import bundle/export/import code.

Likely internal helpers:

- Redacted URI and options-summary helpers.
- Plain-data validation helpers for store refs, capabilities, external
  declarations, published records, and lookup results.
- Capability admission helpers for selected operations such as read reference,
  write/publish, list/lookup, checksum validation, delete, and materialize
  unsupported.
- Fake backend and fake handler fixtures that exercise read-only, writable,
  non-listable, no-checksum, manifest-last, and unknown-capability behavior.
- Compatibility mappers that project Stage 15 summaries into catalog and
  portable-run exchange records.

Data flow:

- Authored config or API input supplies store refs and external/published
  artifact declarations.
- Store handlers validate shape, redact display fields, and report capabilities
  without importing optional dependencies unless explicitly loaded.
- Preflight checks handler availability and required capabilities. Expensive
  network, credential, and payload checks run only when explicitly requested.
- Execution and artifact registration persist `ArtifactRef` plus adjacent
  external/published/location records. Run-store facts remain authoritative;
  cache/staging/materialized locations remain derived.
- Run catalog, bundle/export/import, and portable-run exchange consume the
  stable summaries and preserve metadata without credentials or payload
  downloads by default.

Dependency direction:

- `loom.artifacts` -> serialization/errors/timestamps/fingerprints only.
- `loom.pipeline.stores` -> `loom.artifacts`, `loom.io.uris`, serialization,
  store errors, and existing store protocols.
- `loom.diagnostics` -> public config/runtime/store surfaces for checks.
- `loom.runs` -> public store read models and artifact summaries.
- `loom.plugins` -> explicit loading wrappers around subsystem registries.
- Forbidden: stores importing plugins or runs; artifacts importing stores;
  diagnostics owning store semantics; core importing concrete backend SDKs.

Extension points and flexibility boundaries:

- Stable extension point is a backend handler/factory, not an arbitrary
  `ArtifactStore` instance. Handlers own backend-specific validation,
  redaction, cheap preflight, capability reporting, and optional store opening.
- Backends declare capabilities rather than relying on class names, URI schemes,
  or assumed cloud behavior.
- The contract is generic enough for MLflow-like tracking systems,
  object-store-style backends, HTTP/read-only refs, local published directories,
  and future project-specific adapters.
- Concrete payload upload/download/publish/materialize operations are shaped as
  unsupported/result records in Stage 15 and implemented in Stage 16 or later.

Generic interface, adapter, or protocol shape:

- Handler protocols accept plain config/ref records and return plain
  summaries, diagnostics, capabilities, lookup results, and unsupported
  operation results.
- Loaded Python objects stay separate from serializable summaries so CLI,
  provenance, catalog, and bundle records do not serialize plugin instances.
- Adapter-specific metadata must live under namespaced plain-data fields and
  cannot be required for core behavior unless the generic contract also
  captures the behavior.

Future-roadmap impact:

- Stage 12 rework adopts Stage 15 summaries in portable-run exchange and
  bundle/export/import metadata.
- Stage 14 plugin discovery can support artifact-store backend handlers through
  explicit store-owned adapters once the Stage 15 descriptor/factory, registry,
  and compatibility contracts exist.
- Stage 16 payload materialization consumes capabilities, store refs,
  operation results, staging/cache records, and unsupported diagnostics.
- Stage 17/18 container and HPC execution can use location/capability facts for
  staging and mount decisions without owning remote-store semantics.
- Stage 19 reliability can attach retry/timeout/event records to store
  operations and staging cleanup.
- Stage 20 cleanup/retention can consume retention hints, delete capability,
  and non-authoritative cache/staging facts.

Compatibility constraints:

- Existing `ArtifactRef` dictionaries must continue to load.
- Metadata-only catalog/bundle workflows must not require credentials, network,
  payload availability, or optional backend imports.
- Unknown or missing capabilities must never be treated as supported for
  selected remote writes.
- Redacted display values must be the only form persisted in shareable metadata
  when source values may contain secrets.

## Design Agreement Queue

| ID | Design decision | Recommendation | Status |
| --- | --- | --- | --- |
| DAQ-1 | Artifact ref compatibility strategy | Recorded recommendation: keep broad semantics in adjacent typed records and stable metadata summaries; permit a minimal versioned `ArtifactRef` revision only if it gives concrete validation, compatibility, or ambiguity-reduction guarantees that adjacent records cannot provide. | confirmed |
| DAQ-2 | Store handler package ownership | Recorded recommendation: place artifact identity/location records in `loom.artifacts`, backend contracts/capabilities/registries/fakes in `loom.pipeline.stores`, Stage 12 exchange rework in `loom.runs`, and CLI/preflight as wrappers. | confirmed |
| DAQ-3 | Stage 14 plugin alignment | Recorded recommendation: Stage 15 defines the artifact-store backend descriptor/factory/handler/config/capability target shape, explicit registry behavior, contract/API versioning, and backend diagnostics; Stage 14 owns discovery, entry point constants, metadata-only CLI/preflight listing/check, and generic explicit loading primitives. Use the landed backend-oriented group spelling `loom.artifact_store_backends`; backend availability and run-readiness remain Stage 15 checks. | confirmed after Stage 14 implementation recheck |
| DAQ-4 | Capability model granularity | Recorded recommendation: include operation-specific support records for readable, writable, listable, delete, checksum verification, commit/consistency behavior, and unknown support. Unknown is not sufficient for fail-closed selected writes. | confirmed |
| DAQ-5 | Immutable lookup planner boundary | Recorded recommendation: immutable lookup is explicit, keyed by project-supplied identity and validation policy, and returns structured results for planner consumption only when configured. No automatic global cache lookup. | confirmed |
| DAQ-6 | Preflight and network policy | Recorded recommendation: cheap checks by default; selected remote writes fail closed on missing/unknown required capabilities; network, credential, checksum, and payload probes are opt-in. | confirmed |
| DAQ-7 | Stage 12 exchange rework boundary | Recorded recommendation: include a Stage 15 phase or scoped work item that updates portable-run exchange and bundle/export/import metadata to consume Stage 15 summaries without adding payload materialization. | confirmed |
| DAQ-8 | Examples and adapter pressure tests | Recorded recommendation: include MLflow-like and object-store-style examples as design pressure tests only; no first-party adapter dependency or implementation. | confirmed |
| DAQ-9 | Cache, staging, and materialized locations | Recorded recommendation: model cache/staging/materialized refs as derived/non-authoritative locations with cleanup/reliability hints for later stages. Run-store artifact facts remain authoritative. | confirmed |
| DAQ-10 | Optional dependencies and backend-specific metadata | Recorded recommendation: keep backend-specific metadata namespaced and plain-data; optional dependencies stay in plugin packages or opt-in adapters, never core. | confirmed |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Future-roadmap impact | Interface, adapter, or protocol impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Artifact ref compatibility strategy | Adjacent typed records carry external, published, and multi-location semantics; `ArtifactRef` remains stable unless a narrow versioned revision proves materially better. | User agreed after asking whether revising `ArtifactRef` could improve guarantees. | Encoding all semantics only in untyped metadata; broad top-level `ArtifactRef` schema expansion by default. | Preserves existing persisted refs while allowing typed validation and future schema revision only with concrete benefit. | Avoids breaking local store and run indexes while keeping semantics testable. | Adjacent records can evolve without forcing all refs to become remote-aware. | Stage 12 can consume summaries; Stage 16 can add materialization records; Stage 20 can consume cleanup hints. | Artifact identity records remain broadly reusable; `ArtifactRef` remains the compact produced-output pointer. | Contract tests for old/new ref round-trip, summary projection, and invalid external metadata. | Debt: potential two-record model. Revisit if implementation shows callers cannot enforce location semantics without a minimal top-level field. | confirmed |
| DAQ-2 | Store handler package ownership | Put artifact identity/location records in `loom.artifacts`; backend handlers/capabilities/registry/fakes in `loom.pipeline.stores`; Stage 12 exchange changes in `loom.runs`. | User agreed to Stage 14 alignment and Stage 12 rework. | Put remote-store semantics in `loom.io`; make plugins own store semantics; make bundle/export code own artifact semantics. | Matches existing source-tree direction and keeps lower layers from importing run-exchange or plugin discovery. | Keeps ownership reviewable and prevents circular imports. | Backends, bundle exchange, and diagnostics can all consume stable records. | Preserves Stage 14/16/19/20 flexibility. | Handler protocol remains store-owned; plugin loading wraps it externally. | Import-boundary package tests and docs. | Revisit if `loom.artifacts` module becomes too large and needs a compatibility-preserving package split. | confirmed |
| DAQ-3 | Stage 14 plugin alignment | Stage 15 defines a plugin-loadable descriptor/factory plus normalized handler/config/capability target, explicit registry, contract/API versioning, and backend diagnostics for the landed `loom.artifact_store_backends` group; Stage 14 owns discovery/listing/check mechanics, group constants, and generic entry point loading primitives. | User asked to align with Stage 14, then requested renewed review and later targeted design passes after Stage 14 revised artifact-store backend structure and implementation completed. | Stage 15 implementing discovery; Stage 14 registering arbitrary store instances without a handler contract; using a group name that implies raw `ArtifactStore` instance loading; accepting current local-root `ArtifactStoreFactory` callables as plugin targets; defining a universal plugin object protocol; treating `loom plugins check` listing-only success as backend availability. | Keeps discovery generic while giving adapter authors a concrete target shape. | Avoids duplicate plugin systems, raw-instance coupling, local-root construction lock-in, premature universal object contracts, and false run-readiness claims. | Store-owned plugin adapters can normalize loaded descriptors/factories into a supplied registry without changing store semantics or Stage 14 metadata-only CLI/preflight behavior. | Stage 16 consumes the resulting registry/capability contract for materialization; later plugin readiness can be widened only with config-aware backend checks. | Descriptor/factory/handler/config/capability protocol is the reusable store adapter contract; registry adapters stay contract-specific and supplied-registry-based. | Stage 15 descriptor/handler contract tests; docs/examples use `loom.artifact_store_backends`; validation covers programmatic registry use without plugins and proves Stage 14 metadata/import checks do not imply backend availability. | Debt: Stage 14 generic plugin diagnostics still classify artifact-store backends as listing-only. Revisit only if Stage 15 adds a config-aware plugin adapter and can update readiness wording without implying run-readiness. | confirmed after Stage 14 implementation recheck |
| DAQ-4 | Capability model granularity | Use operation-specific support records with supported/unsupported/unknown plus details for read, write, list, delete, checksum verification, commit/consistency, and materialization support. | User confirmed fail-closed selected remote writes. | Bare booleans only; scheme-based assumptions; treating unknown as supported. | Capability-aware behavior is the central remote-store safety contract. | More fields, but avoids scattered backend assumptions. | New operations can be added as records without changing every handler. | Stage 16 materialization, Stage 19 reliability, and Stage 20 cleanup consume capability facts. | Capabilities become plain-data adapter contract. | Unit tests for admission and unknown support; fake backends for supported/unsupported matrices. | Revisit if capability records duplicate authority capability types enough to justify shared helper extraction. | confirmed |
| DAQ-5 | Immutable lookup planner boundary | Lookup is explicit and returns compatible/incompatible/missing/unsupported results validated by key, type, schema, checksum/fingerprint, and policy. | User agreed to generic interface scope. | Automatic global cache lookup; implicit planner reuse; domain-specific cache keys in core. | Keeps reuse useful but not surprising or domain-specific. | Central result model avoids ad hoc planner hooks. | Later project/backends can supply lookup adapters without changing planner defaults. | Stage 16 can materialize compatible refs explicitly; reliability can record lookup events later. | Lookup request/result is adapter-neutral. | Contract tests for validation paths and planner handoff. | Revisit when a real adapter shows missing validation facts. | confirmed |
| DAQ-6 | Preflight and network policy | Cheap checks by default; selected remote write backends fail closed on missing/unknown required capabilities; expensive probes opt-in. | User agreed. | Always probing credentials/network; warning-only selected remote writes; never checking capabilities. | Balances reproducibility with local/offline testability. | Keeps preflight deterministic by default. | Optional check policies can grow without changing default behavior. | Stage 16 can add opt-in payload/materialization probes. | Preflight consumes capabilities and handler diagnostics. | Preflight unit/integration tests with fake handlers; no network default assertions. | Revisit if downstream deployments need named preflight policy profiles. | confirmed |
| DAQ-7 | Stage 12 exchange rework boundary | Stage 15 includes scoped Stage 12 metadata rework for portable-run exchange and bundle/export/import; no payload materialization. | User said Stage 12 rework is important and should be included. | Leaving Stage 12 opaque forever; moving bundle semantics into stores; adding remote downloads. | Prevents incompatible durable bundle fields after external refs become first-class. | Keeps exchange changes reviewable and avoids later migration churn. | Portable-run exchange becomes a consumer of generic artifact summaries. | Stage 12 artifacts become compatible with Stage 15/16 external refs. | Exchange records adopt summary/result protocols. | Contract tests for round-trip metadata-only refs and unsupported materialization diagnostics. | Revisit during phase planning if current `src/loom/runs` exchange extension fields cannot carry Stage 15 summaries without schema widening. | confirmed after Stage 12 source recheck |
| DAQ-8 | Examples and adapter pressure tests | Use MLflow-like and object-store-style examples only as docs/design fixtures and contract fixtures when executable without optional dependencies. | User agreed. | Implementing MLflow/S3; using only one example; domain-specific examples; auto-approving examples without validating both tracking-system indirection and object-store consistency semantics. | Two contrasting examples challenge genericity without dependencies and are material enough to record as a recommendation. | Keeps examples useful while avoiding service code. | Helps adapter authors map future backends without overfitting the public contract. | Validates Stage 14/16 compatibility assumptions and preserves optional adapter flexibility. | Examples exercise handler, capability, redaction, unsupported-operation, lookup, and record-summary contracts. | Docs/example fixtures and design-safety checklist; no installed MLflow/cloud packages in default tests. | Revisit when first real adapter is selected or examples start requiring backend-specific fields for core behavior. | confirmed |
| DAQ-9 | Cache, staging, and materialized locations | Model as derived/non-authoritative location records with cleanup/reliability hints. | User agreed to metadata-first behavior. | Treating cache as source of truth; omitting staging facts until materialization. | Future materialization and cleanup need records, but authority must stay clear. | Avoids conflating payload availability with lifecycle truth. | Later stages can attach retry, cleanup, and retention policy. | Stage 16/19/20 consume records. | Location summaries include authoritative/derived distinction. | Tests for cache/staging not being used as authoritative lookup evidence. | Revisit when materialization semantics land. | confirmed |
| DAQ-10 | Optional dependencies and backend metadata | Keep backend-specific facts namespaced and plain-data; optional dependencies stay outside core. | User confirmed no concrete backends. | Importing SDKs in core; requiring MLflow/DVC schemas in generic records. | Preserves import-light and domain-neutral core. | Prevents dependency churn and import failures. | Backend packages can evolve independently. | Stage 14 plugin loading and Stage 16 adapters remain optional. | Handler summaries separate loaded objects from serialized facts. | Package import tests and docs. | Revisit when an optional adapter family is explicitly selected. | confirmed |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Could top-level `ArtifactRef` fields improve validation? Yes, but adjacent records preserve compatibility while keeping a narrow revision gate. | FR-1, FR-4, FR-7 | Reviewed and upheld in design-safety review | confirmed |
| DAQ-2 | recorded recommendation | Could a new package be cleaner? Current module/package boundaries favor minimal churn and import safety. | FR-1, FR-5, FR-7, FR-9 | Reviewed and upheld in design-safety review | confirmed |
| DAQ-3 | recorded recommendation | Could Stage 15 depend directly on Stage 14? Yes, but only on the landed discovery/readiness primitives: `loom.artifact_store_backends`, `PluginRecord`, generic listing/loading helpers, and listing-only CLI/preflight metadata. Stage 15 still owns the contract-specific descriptor/factory/handler/config/capability registry target plus contract/API versioning. | FR-5, FR-8 | Updated planning for completed Stage 14 implementation and send to implementation-plan drafting | confirmed after Stage 14 implementation recheck |
| DAQ-4 | recorded recommendation | Could capability records be too broad? Fields map directly to confirmed behavior and future roadmap consumers. | FR-1, FR-5, FR-6 | Reviewed and upheld with unknown-support obligation | confirmed |
| DAQ-5 | recorded recommendation | Could lookup become implicit cache reuse? Boundary explicitly forbids automatic global cache lookup. | FR-3 | Reviewed and upheld in design-safety review | confirmed |
| DAQ-6 | recorded recommendation | Could fail-closed block metadata-only flows? Only selected remote writes fail closed; metadata-only remains cheap. | FR-6 | Reviewed and upheld in design-safety review | confirmed |
| DAQ-7 | recorded recommendation | Could Stage 12 rework expand scope too far? Scope is metadata alignment only, no payload materialization. | FR-7, FR-9 | Reviewed and upheld with current Stage 12 extension-field recheck | confirmed |
| DAQ-8 | recorded recommendation | Could examples bias the design? Pairing MLflow-like and object-store-style examples counterbalances that risk, but the examples still shape public adapter expectations and should not remain auto-approved. | FR-8, FR-10 | Reclassify as recorded recommendation with validation obligations | confirmed |
| DAQ-9 | recorded recommendation | Could staging/cache records prematurely design Stage 16? Records only classify derived locations and cleanup hints. | FR-4 | Reviewed and upheld with descriptive-record-only obligation | confirmed |
| DAQ-10 | recorded recommendation | Could namespaced backend metadata become a dumping ground? Validation and docs must define core-owned versus backend-owned fields. | FR-1, FR-8, FR-10 | Reviewed and upheld with redaction and core-field boundary obligations | confirmed |

## Design Safety Review

Review status:

- Reviewer: project-scoped `loom_design_safety_reviewer`, invoked by the
  managing Codex session for Stage 15 planning.
- Review date: 2026-05-15.
- Target artifact: `docs/roadmap/stage-15/planning.md`.
- Sources checked: `AGENTS.md`, `docs/roadmap.md` v15/v16/v19/v20 and
  adjacent v12/v14 sections, `docs/roadmap/stage-14/planning.md`,
  `docs/roadmap/stage-12/planning.md`,
  `docs/roadmap/stage-12/implementation-plan.md`, `docs/structure.md`,
  `docs/GLOSSARY.md`, `docs/features/remote-stores.md`,
  `docs/features/artifacts.md`, `docs/features/plugins.md`,
  `docs/features/preflight.md`, `docs/features/run-catalog.md`,
  `docs/features/io.md`, `docs/features/reliability.md`,
  `docs/features/testing.md`, `src/loom/artifacts.py`,
  `src/loom/pipeline/stores/artifact_store.py`,
  `src/loom/pipeline/stores/local_artifacts.py`,
  `src/loom/pipeline/stores/capabilities.py`, and current diagnostics and
  portable-run exchange references.
- Gate result: passed with required planning revisions recorded below. No
  `blocked` or `needs discussion` decision remains from design-safety review.
  Renewed review after the Stage 14 planning revisions also passed with no
  blocker or `needs discussion` decision. Examples/validation and phase shaping
  were later confirmed in their sections below. The later post-implementation
  alignment review below supersedes the original Stage 14 implementation-absent
  dependency.

Findings:

| Severity | Finding | Evidence | Required planning revision or action | Status |
| --- | --- | --- | --- | --- |
| Required revision | Stage 14 was no longer only a draft planning dependency; Stage 15 had to use the confirmed backend-oriented group spelling and recheck implementation artifacts before coding. | `docs/roadmap/stage-14/planning.md` records design-safety passed and revises artifact-store plugin metadata to `loom.artifact_store_backends`. | Update Stage 15 metadata, source evidence, DAQ-3, accepted debt, and examples/validation obligations to use `loom.artifact_store_backends` and retain a recheck trigger for Stage 14 implementation plan, loader contracts, and landed code. | superseded by post-implementation alignment review |
| Required revision | Stage 12 rework scope is valid but must be tied to the current portable-run exchange plan, where external refs are opaque extension fields until Stage 15 summaries land. | `docs/roadmap/stage-12/implementation-plan.md` Phase 1 records strict manifest records with extension fields for opaque external refs; Stage 15 FR-9 requires replacing opaque refs with stable metadata records. | Implementation-plan drafting must include a scoped Stage 12 metadata rework phase or work item that maps existing portable-run extension fields to Stage 15 summaries without adding payload materialization or authority mutation. | recorded |
| Required revision | The handler/factory contract is reusable only if it separates metadata/config/ref checks from payload operations that belong to Stage 16. | `docs/roadmap.md` v15 owns interface and unsupported-operation records; v16 owns materialization, publish, upload, and download. `docs/features/remote-stores.md` lists put/get/write operations, but Stage 15 planning defers real transfer paths. | Handler protocols must be metadata/check/lookup/preflight oriented in Stage 15, with open/materialize/publish/upload/download represented as structured unsupported or capability-gated results unless a later stage implements them. | recorded |
| Required revision | Capability records need a three-state or equivalent support model, not only booleans, because fail-closed selected writes depend on distinguishing unknown from unsupported and supported. | Stage 15 DAQ-4 already records supported/unsupported/unknown; `docs/features/remote-stores.md` shows an older boolean example; current authority capabilities use explicit support records but no unknown state. | Keep Stage 15 capability records operation-specific and capable of representing unknown, unsupported, supported, and explanatory diagnostics; do not reuse authority capability types directly unless they can preserve this distinction. | recorded |
| Required revision | Namespaced backend metadata is acceptable only with core-owned field boundaries and redaction rules; otherwise it can become a public contract escape hatch. | DAQ-10 permits namespaced metadata; `remote-stores.md` requires no credential storage and redacted diagnostics; `ArtifactRef.metadata` is plain but untyped. | Planning and implementation must define core-owned summary fields versus backend-owned namespaced detail fields, reject secret-bearing persisted values, and validate that core behavior never requires backend-specific namespaced fields. | recorded |
| Required revision | Cache/staging/materialized location records must not design hidden cleanup or retry policy early. | V16 owns payload movement; V19 owns retry/timeout/events; V20 owns cleanup/retention. `reliability.md` and `docs/roadmap.md` require recorded temporary paths, explicit cleanup, and conservative deletion. | Keep Stage 15 records descriptive: location kind, authoritative/derived status, optional retention/cleanup hints, and unsupported operation diagnostics only. Retry policies, cleanup deletion, and payload lifecycle behavior remain later-stage work. | recorded |
| Note | The adjacent-record-first `ArtifactRef` strategy is safe enough for implementation-plan drafting if summary projection and old-ref round trips are mandatory validation. | `ArtifactRef.from_dict` rejects unknown top-level fields; current local store and run indexes expect compact produced-output refs. | Preserve DAQ-1 as a recorded recommendation. Permit a minimal `ArtifactRef` revision only if implementation planning proves adjacent summaries cannot enforce validation or unambiguous persisted semantics. | upheld |
| Note | MLflow-like and object-store-style examples are necessary pressure tests, not harmless examples. | User asked for MLflow-like plus object-store-style coverage; the examples shape adapter expectations for tracking indirection, object-store consistency, checksums, listing, delete, and unsupported operations. | Reclassify DAQ-8 from auto-approved candidate to recorded recommendation with explicit no-dependency and validation obligations. | recorded |

Design decision classifications after safety review:

| Decision | Classification | Review result |
| --- | --- | --- |
| DAQ-1 Artifact ref compatibility strategy | recorded recommendation | Upheld. Adjacent typed records remain the default; narrow `ArtifactRef` revision remains gated by concrete validation or compatibility benefit. |
| DAQ-2 Store handler package ownership | recorded recommendation | Upheld. `loom.artifacts`, `loom.pipeline.stores`, `loom.runs`, `loom.plugins`, `loom.diagnostics`, and CLI boundaries remain consistent with `docs/structure.md`. |
| DAQ-3 Stage 14 plugin alignment | recorded recommendation | Upheld with revision. Use `loom.artifact_store_backends`; later post-implementation review confirmed the landed Stage 14 API and listing-only artifact-store backend boundary. |
| DAQ-4 Capability model granularity | recorded recommendation | Upheld with revision. Unknown support must remain representable and fail closed for selected writes. |
| DAQ-5 Immutable lookup planner boundary | recorded recommendation | Upheld. Explicit lookup does not become automatic global cache reuse or partial stage reuse. |
| DAQ-6 Preflight and network policy | recorded recommendation | Upheld. Cheap default checks plus opt-in network/credential/payload probes remain the safe default. |
| DAQ-7 Stage 12 exchange rework boundary | recorded recommendation | Upheld with revision. Rework must target current portable-run exchange extension fields and stay metadata-only. |
| DAQ-8 Examples and adapter pressure tests | recorded recommendation | Revised from auto-approved candidate. Examples are required design pressure tests with validation obligations and no first-party dependency. |
| DAQ-9 Cache, staging, and materialized locations | recorded recommendation | Upheld with revision. Records stay descriptive/non-authoritative; cleanup/retry behavior remains V19/V20. |
| DAQ-10 Optional dependencies and backend-specific metadata | recorded recommendation | Upheld with revision. Namespaced details must not become required core semantics or persist secrets. |

### Renewed Stage 14 Alignment Addendum

Review status:

- Reviewer: project-scoped `loom_design_safety_reviewer`, invoked by the
  managing Codex session for renewed Stage 15 design-safety review after Stage
  14 planning revisions.
- Review date: 2026-05-15.
- Trigger: user requested renewed review with focus on the revised Stage 14
  plugin structure, especially `loom.artifact_store_backends` and Stage 14's
  registry-adapter pattern.
- Sources rechecked: `docs/roadmap/stage-15/planning.md`,
  `docs/roadmap/stage-14/planning.md`, `docs/structure.md`,
  `docs/GLOSSARY.md`, `docs/features/plugins.md`,
  `docs/features/remote-stores.md`, `docs/features/artifacts.md`,
  `src/loom/artifacts.py`, `src/loom/pipeline/stores/artifact_store.py`, and
  nearby store capability/local-artifact docs and source.
- Gate result: passed. No blocker or `needs discussion` item remains from the
  renewed Stage 14 alignment review.

Findings:

| Severity | Finding | Evidence | Required planning revision or action | Status |
| --- | --- | --- | --- | --- |
| Required revision | Stage 14's revised plugin structure strengthens, rather than weakens, the need for a Stage 15-owned artifact-store backend registry contract. | Stage 14 classifies `loom.artifact_store_backends` as listing/check-only until Stage 15 lands backend config, handler, capability, and registry semantics. The current `ArtifactStore` protocol is run/local-operation oriented and is not a plugin-loadable backend descriptor. | Stage 15 must define a stable handler/factory/config/capability/registry shape keyed by backend kind. Programmatic registry registration remains first-class; Stage 14 loaders later adapt selected entry points into that registry. | recorded |
| Required revision | The Stage 14 registry-adapter pattern must stay contract-specific for artifact stores. | Stage 14 records the generic pattern as metadata listing, selected explicit load, contract-specific normalization, caller-supplied registry registration, and structured result. It explicitly rejects a universal object protocol. | Artifact-store plugins must not be documented as arbitrary objects with common plugin methods. The Stage 15 handler/factory contract owns accepted object shape, config handoff, keys, duplicate policy, diagnostics, and optional operation opening. | recorded |
| Note | Adjacent-record-first `ArtifactRef` strategy remains the safest default. | `ArtifactRef.from_dict` rejects unknown top-level fields; the local store and existing run indexes depend on compact produced-output refs. Stage 15 needs external/published/multi-location guarantees, but those can be provided by strict adjacent summaries plus validation. | Keep DAQ-1 unchanged. A minimal versioned `ArtifactRef` revision remains allowed only if implementation planning proves adjacent records cannot provide a concrete guarantee such as unambiguous location kind, validation enforcement, or compatibility-safe summary projection. | upheld |
| Note | Stage 12 rework remains metadata-only. | Stage 12 external refs are planned as opaque extension fields until Stage 15 summaries exist; Stage 16 owns payload materialization, publish, upload, and download. | Stage 15 may replace opaque bundle/catalog/exchange summaries and unsupported-materialization diagnostics, but must not add downloads, credential access, or payload transfer behavior to Stage 12 exchange work. | upheld |
| Note | Stage 16+ materialization concerns are design inputs, not Stage 15 behavior. | `remote-stores.md` discusses remote put/get/staging/cache concepts, while roadmap v16+ owns materialization and later reliability/cleanup stages own retries and deletion. | Stage 15 handler contracts may expose capability facts and unsupported-operation results that future materialization can consume, but implementation planning must keep payload operations capability-gated or unsupported. | upheld |

Decision/status updates from renewed review:

| Decision | Renewed classification | Result |
| --- | --- | --- |
| DAQ-1 Artifact ref compatibility strategy | recorded recommendation | Upheld. Adjacent typed records remain default; minimal `ArtifactRef` revision is still a narrow guarantee-driven escape hatch. |
| DAQ-3 Stage 14 plugin alignment | recorded recommendation | Strengthened. Stage 15 must define handler/factory/config/capability registry semantics for `loom.artifact_store_backends`; Stage 14 remains discovery, metadata diagnostics, and generic explicit loading primitives only. |
| DAQ-7 Stage 12 exchange rework boundary | recorded recommendation | Upheld. Rework is stable metadata adoption only, with no credential, network, or payload materialization behavior. |
| DAQ-10 Optional dependencies and backend-specific metadata | recorded recommendation | Upheld. Backend-specific details stay namespaced/plain-data and cannot be required for core behavior. |

### Latest Stage 14 Artifact-Store Backend Addendum Pass

Review status:

- Reviewer: managing Codex local design pass for Stage 15 after the latest
  Stage 14 artifact-store backend addendum.
- Review date: 2026-05-15.
- Trigger: user reported another Stage 14 revision and requested another
  design pass with respect to it.
- Sources rechecked: `docs/roadmap/stage-14/planning.md`,
  `docs/roadmap/stage-15/planning.md`, `docs/features/remote-stores.md`,
  current `ArtifactRef`, `ArtifactStore`, `LocalArtifactStore`, and runner
  artifact-store construction references.
- Gate result: passed. No blocker or `needs discussion` item remains from the
  latest Stage 14 artifact-store backend design pass.

Findings:

| Severity | Finding | Evidence | Required planning revision or action | Status |
| --- | --- | --- | --- | --- |
| Required revision | Stage 14 now makes artifact-store backend metadata-only behavior explicit enough that Stage 15 must define the first loadable backend contract, not merely refine a Stage 14 loader. | Stage 14 says `loom.artifact_store_backends` is a stable advertisement and diagnostics namespace only, with no backend loader, no store registry mutation, no raw `ArtifactStore` or local-root factory plugin target, and no run-readiness claim. | Stage 15 must define the store-owned descriptor/factory plus normalized handler/registry contract before `loom.plugins` can load artifact-store backends. The contract must include backend kind/key policy, config and run-context handoff, duplicate handling, operation/failure records, and capability reporting. | recorded |
| Required revision | The Stage 15 public backend contract needs contract/API versioning to avoid future refactors when optional adapters arrive. | Stage 14's addendum recommends a Stage 15 descriptor/factory and explicitly names contract/API version validation before registration. | Stage 15 should include a versioned descriptor/factory shape or equivalent compatibility guard so future backend packages can be rejected or adapted deterministically without changing discovery or registry APIs. | recorded |
| Required revision | Stage 14 plugin checks and Stage 15 backend availability checks must remain distinct. | Stage 14 metadata checks can list, duplicate-check, and optionally import-check future backend entry points, but they are not registration, capability validation, or run-readiness checks. | Stage 15 must define separate preflight/backend check IDs and diagnostics for configured backend availability, URI/config validation, capability admission, and selected remote write fail-closed behavior. A Stage 14 import-only success must not satisfy these checks. | recorded |
| Required revision | Current local artifact-store construction hooks are not the public backend plugin contract. | `PipelineRunner` currently receives a local-root `ArtifactStoreFactory`; Stage 14 rejects raw `ArtifactStore` and local-root factory plugin targets. | Stage 15 must define run-context store construction through explicit backend config and store-owned resolution. Pipeline/runtime code should consume resolved store factories without importing plugin discovery or accepting plugin targets directly. | recorded |
| Note | The latest Stage 14 revision does not change the adjacent-record-first `ArtifactRef` conclusion. | Artifact-store backend loading remains a store/config/registry concern; external, published, and multi-location semantics still need strict plain-data summaries around the compact `ArtifactRef`. | Keep DAQ-1 unchanged, with a minimal `ArtifactRef` revision still allowed only for a concrete guarantee adjacent summaries cannot provide. | upheld |

Decision/status updates from latest pass:

| Decision | Latest classification | Result |
| --- | --- | --- |
| DAQ-1 Artifact ref compatibility strategy | recorded recommendation | Upheld. The Stage 14 backend addendum affects plugin/loadable backend shape, not persisted artifact identity strategy. |
| DAQ-3 Stage 14 plugin alignment | recorded recommendation | Strengthened again. Stage 15 owns the first loadable artifact-store backend descriptor/factory, contract/API versioning, supplied registry, backend diagnostics, and run-context construction handoff. |
| DAQ-4 Capability model granularity | recorded recommendation | Upheld with sharper boundary. Unknown backend capability remains fail-closed for selected writes, and Stage 14 metadata/import checks cannot turn unknown into supported. |
| DAQ-6 Preflight and network policy | recorded recommendation | Upheld with sharper boundary. Stage 15 backend preflight/check IDs must be separate from Stage 14 plugin metadata checks and must avoid default network, credential, or payload probes. |

### Post-Stage 14 Implementation Alignment Review

Review status:

- Reviewer: managing Codex local review after Stage 14 implementation
  completion.
- Review date: 2026-05-15.
- Trigger: user reported `docs/roadmap/stage-14/implementation-plan.md` is
  complete and requested Stage 15 planning update/review before converting to
  an implementation plan.
- Sources rechecked: `docs/roadmap/stage-14/implementation-plan.md`,
  `docs/features/plugins.md`, `src/loom/plugins/entrypoints.py`,
  `src/loom/plugins/diagnostics.py`, `src/loom/plugins/__init__.py`,
  targeted plugin tests, `src/loom/runs/models.py`,
  `src/loom/runs/bundles.py`, and run-exchange contract tests.
- Gate result: passed. No blocker or `needs discussion` item remains for
  implementation-plan drafting.

Findings:

| Severity | Finding | Evidence | Planning update or implementation-plan obligation | Status |
| --- | --- | --- | --- | --- |
| Required update | Stage 14 is now a landed public API dependency, not only a planning assumption. | Stage 14 plan records all phases merged; `src/loom/plugins` exports `LOOM_ARTIFACT_STORE_BACKENDS_GROUP = "loom.artifact_store_backends"` and readiness metadata. | Stage 15 metadata, source evidence, DAQ-3, accepted debt, and implementation-plan context now refer to completed Stage 14 and the landed group/readiness API. | recorded |
| Required boundary | Artifact-store backend plugin entries remain listing-only for Stage 14 CLI/preflight diagnostics. | `LOADABLE_PLUGIN_GROUPS` contains only `loom.recipes` and `loom.codecs`; `plugin_group_readiness(loom.artifact_store_backends).status` is `listing-only`; no `load_artifact_store_backend_entry_points` is exported. | Stage 15 may use generic entry point primitives and define a supplied-registry adapter, but Stage 14 metadata/list/import checks must not be treated as backend availability, capability admission, or run-readiness. | recorded |
| Required boundary | Generic `load_entry_points(...)` is available, but it is not the artifact-store backend contract. | Stage 14's generic loader imports selected targets and can call a registration callback, while diagnostics load only registry-ready groups. | Stage 15 backend adapters must normalize loaded descriptor/factory objects into a store-owned registry with contract/API versioning; raw `ArtifactStore`, local-root factories, plugin-owned registries, and universal plugin objects stay rejected. | recorded |
| Required update | Stage 12 exchange APIs are concrete enough for a scoped metadata rework. | `RunBundleManifest`, `PortableRunExportRecord`, `PortableRunImportRecord`, exchange results, and payload selection records include strict plain-data schemas with `extensions`; local bundle export builds manifests from completed-run metadata. | Phase shaping and implementation-plan Phase 5 should map Stage 15 external/published/location summaries into run-exchange extension fields or a narrow schema revision without downloads, credentials, payload access, or authority mutation. | recorded |

Decision/status updates from post-implementation review:

| Decision | Result |
| --- | --- |
| DAQ-3 Stage 14 plugin alignment | Confirmed against landed code. Stage 15 depends on group constants, generic metadata/list/load primitives, and readiness summaries only; it owns backend descriptor/factory, registry, capabilities, backend availability checks, and run-context handoff. |
| DAQ-7 Stage 12 exchange rework boundary | Confirmed against landed source APIs. Rework remains metadata-only and should consume existing strict records and extension points unless implementation proves a minimal schema revision is necessary. |
| DAQ-8 Examples and adapter pressure tests | Confirmed. MLflow-like and object-store-style examples must exercise the same generic contracts and must not require optional packages. |

Accepted risks:

| Risk | Why accepted | Revisit trigger |
| --- | --- | --- |
| Stage 14 plugin diagnostics still classify artifact-store backends as listing-only. | That avoids false backend availability or run-readiness until Stage 15 defines configured backend registry/capability checks. | Stage 15 lands a supplied-registry backend adapter and can update plugin docs/readiness wording without making CLI/preflight metadata checks imply run-readiness. |
| Stage 12 run-exchange external artifact facts currently fit through generic extension fields. | Existing strict records preserve forward-compatible extension points without forcing payload materialization. | Implementation proves external artifact summaries need a narrow versioned schema field to avoid ambiguous exchange semantics. |
| Adjacent artifact records introduce two-record coordination. | This preserves persisted `ArtifactRef` compatibility and local-store behavior while adding typed semantics. | Callers cannot enforce location semantics, summary projection becomes ambiguous, or compatibility tests show a top-level versioned `ArtifactRef` field would reduce risk. |
| Capability model may overlap authority capability records. | Artifact-store capabilities are about payload/ref operations and consistency, not authority lifecycle truth; reusing style is safer than conflating types. | Duplicate helpers become substantial, or authority capability types gain a generic support-state model suitable for extraction without coupling stores to authority. |
| Backend-specific namespaced metadata can accumulate. | Namespaced plain data is necessary for arbitrary adapters, but core-owned summary fields and redaction rules bound its use. | A planned core behavior requires backend-specific fields, or persisted metadata includes secrets, SDK objects, or non-plain values. |

Design-safety validation obligations for later planning gates:

- Examples must include one MLflow-like mapping and one object-store-style
  mapping that both use the same store ref, capability, handler, lookup,
  redaction, and unsupported-operation contracts.
- Default tests must use fake handlers/backends only; no installed MLflow,
  cloud SDK, network, container, or service dependency is allowed.
- Package/import-boundary tests must prove `loom.artifacts` does not import
  stores/diagnostics/plugins/runs, stores do not import plugin discovery or
  bundle internals, and plugin loading is explicit.
- Contract tests must cover old `ArtifactRef` round trip, adjacent summary
  projection, capability admission including unknown support, duplicate/missing
  handler diagnostics, metadata-only bundle/catalog preservation, and
  unsupported materialization diagnostics.
- Store registry tests must cover programmatic registration independent of
  plugins and a fake Stage 14-style registry adapter that normalizes a loaded
  handler/factory into the supplied `ArtifactStoreBackendRegistry` without
  accepting arbitrary raw `ArtifactStore` instances.
- Descriptor/factory contract tests must cover contract/API version
  compatibility, backend kind/key normalization, supported URI-scheme
  declarations, config validation/redaction, run-context handoff, and rejection
  of raw `ArtifactStore` instances or current local-root `ArtifactStoreFactory`
  callables as plugin targets.
- Plugin metadata/import-only diagnostics must not satisfy Stage 15 backend
  availability checks. Tests should prove a listed or importable
  `loom.artifact_store_backends` entry still requires Stage 15 registration,
  capability admission, and configured backend preflight before use.
- Preflight tests must cover stable check IDs for handler availability,
  URI/config validation, capability admission, selected remote write
  fail-closed behavior, and no default network or payload access.

## Practical Design Notes

Public Python API surface:

- Prefer small dataclass-style plain-data records and protocols exported through
  existing public package surfaces. Keep loaded backend objects separate from
  serializable summaries.

CLI surface:

- No new Stage 15 command family by default. Existing `preflight`, artifact
  inspection, run catalog, and bundle/export/import surfaces present the new
  facts where they already own user workflows.

Persisted records and file layout:

- Persist stable external/published/location summaries in run-store artifact
  facts, catalog projections, and portable-run exchange/bundle manifests.
  Avoid storing credentials, loaded objects, or backend SDK-specific blobs.

Import boundaries and dependencies:

- No optional backend SDKs in core. No plugin discovery on import. No store
  imports from `loom.runs` or `loom.plugins`.
- Store-owned resolution may consume a backend registry supplied by outer setup
  code, but `ArtifactStore`, `LocalArtifactStore`, pipeline runner lifecycle
  code, and default preflight paths must not import plugin discovery or accept
  plugin entry point targets directly.

Failure modes and diagnostics:

- Missing handler, duplicate handler, unsupported operation, unknown required
  capability, invalid/redaction-unsafe URI, checksum/fingerprint mismatch, and
  materialization-unavailable are structured diagnostics.
- Incompatible backend descriptor contract/API versions, metadata-only plugin
  entries, import-only diagnostic success, and premature run-readiness requests
  are also structured diagnostics. Plugin metadata success must not be reported
  as backend availability.

Extension points and flexibility boundaries:

- Store-owned backend descriptors/factories normalized into handlers are the
  extension point. Core records express generic facts; backends own
  backend-specific validation. Stage 14 plugin loading is only an optional
  adapter into the supplied registry after this contract exists.

Generic interfaces, adapters, and protocols:

- Protocols should accept and return plain records, not concrete SDK clients or
  service objects. This keeps MLflow-like, object-store-style, HTTP read-only,
  local published directory, and future project adapters on the same shape.
- Public backend descriptors should expose a small, versioned contract surface:
  backend kind/key, supported URI schemes, config validation/redaction,
  capability reporting, preflight hooks, and run-context construction handoff.
  They should not expose service-client lifetimes as core API.

Future-roadmap compatibility:

- Stage 15 records are the durable bridge from Stage 12 bundles to Stage 16
  materialization and later reliability/cleanup stages.

Maintainability assessment:

- The shape adds several records, but keeps each ownership boundary narrow:
  identity in artifacts, backend behavior in stores, exchange in runs, and
  discovery in plugins.

Extensibility assessment:

- Handler/capability/result records leave room for optional adapters without
  broad core dependencies or service-specific APIs.

Flexibility and expansion assessment:

- Unknown capabilities, namespaced metadata, explicit lookup, and unsupported
  operation results provide room for backend differences without weakening
  default safety.

Scalability and future compatibility:

- Metadata-only defaults scale to large artifacts and unavailable backends.
  Payload movement waits for explicit Stage 16 materialization.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Stage 14 plugin diagnostics classify artifact-store backends as listing-only. | This is the correct default until Stage 15 defines configured backend registry/capability checks; it prevents metadata checks from implying backend availability. | Stage 15 lands a supplied-registry backend plugin adapter and can update plugin docs/readiness wording without making CLI/preflight metadata checks imply run-readiness. |
| Adjacent records may require callers to carry both `ArtifactRef` and location summaries. | Preserves persisted ref compatibility while adding validation. | If implementation cannot enforce location semantics without top-level fields. |
| Stage 12 exchange rework currently uses generic extension fields for future external refs. | User wants rework included and Stage 15 needs to prevent opaque-ref lock-in while avoiding payload materialization. | Phase planning finds that extension fields cannot carry Stage 15 summaries clearly enough and records a minimal schema revision instead. |
| Stage 15 capability records may overlap authority capability style. | Artifact-store capabilities need unknown/unsupported/supported semantics for payload/ref operations that authority lifecycle records do not currently own. | Extract shared helpers only if this can happen without coupling artifact stores to authority or losing unknown-support semantics. |

## Examples And Validation Strategy

Examples:

- MLflow-like tracking-system artifact adapter example:
  - Purpose: pressure-test tracking-system indirection without adding an
    MLflow dependency or a domain-specific core API.
  - Mapping: a fake descriptor advertises a tracking-style backend kind,
    contract/API version, redacted tracking URI, artifact URI pattern, run
    identity fields, supported URI schemes, and config validation. It
    normalizes into `ArtifactStoreBackendRegistry` through the Stage 15
    descriptor/factory contract.
  - External input: an authored immutable input declaration references a
    tracking run/artifact path through `ArtifactStoreRef` plus
    `ExternalArtifactDeclaration`, with type, schema version,
    checksum/fingerprint facts, immutability assertion, and namespaced
    backend details.
  - Published output: a published record maps producer provenance, project
    reuse key, validation policy, checksum/fingerprint evidence, and
    unsupported materialization diagnostics without uploading payloads.
  - Capability expectations: read/list may be supported or unknown by the fake
    backend; write/delete/materialize are explicit support records rather than
    assumed from scheme. Selected write with unknown capability fails closed.
  - Redaction: credentials, tokens, and service-specific connection details do
    not persist in summaries, CLI output, catalog rows, bundle manifests, or
    preflight diagnostics.
- Object-store-style artifact adapter example:
  - Purpose: pressure-test object-addressed artifact refs, eventual
    consistency hints, checksum facts, listing behavior, duplicate backend
    names, and unsupported operations with the same generic contracts.
  - Mapping: a fake descriptor advertises an object-store-style backend kind,
    contract/API version, supported object URI schemes, bucket/root config,
    redacted display URI, config validation, capability records, consistency
    hints, and manifest/commit policy facts.
  - External input: a stable object URI becomes a metadata-only external
    artifact declaration with checksum/fingerprint validation policy and
    backend-owned namespaced details.
  - Published output: an immutable output record uses a project-supplied reuse
    key and validation evidence; Stage 15 records lookup results but does not
    upload, download, delete, or garbage collect payloads.
  - Capability expectations: read/write/list/delete/checksum verification are
    operation-specific support records. Unknown or unsupported selected writes
    fail preflight; metadata-only preservation remains allowed.
  - Consistency: consistency and commit-policy hints are descriptive inputs for
    later Stage 16/19 behavior, not hidden retry, staging, or cleanup policy.

Validation strategy:

- Package and import-boundary tests:
  - `loom.artifacts` must not import stores, diagnostics, plugins, or runs.
  - Store contracts may depend on artifact value objects but must not import
    plugin discovery or bundle internals.
  - `import loom`, CLI help, and default preflight paths must not discover or
    load backend plugin targets.
- Plain-data and schema tests:
  - Old `ArtifactRef` round trips continue to pass.
  - External, published, and location summaries validate strict plain data,
    reject unknown or secret-bearing core fields, preserve namespaced backend
    details, and project to/from stable metadata summaries.
  - Adjacent summaries prove enough guarantees for location kind,
    validation-policy enforcement, and compatibility-safe persistence. If they
    cannot, implementation-plan drafting must record a minimal versioned
    `ArtifactRef` revision and the compatibility reason.
- Backend descriptor/factory and registry contract tests:
  - Descriptor/factory contract/API version compatibility is checked before
    registration.
  - Backend kind/key normalization, supported URI-scheme declarations, config
    validation/redaction, run-context handoff, duplicate handling, and missing
    handler diagnostics are deterministic.
  - Programmatic registration works without plugins.
  - A fake Stage 14-style adapter can normalize a loaded descriptor/factory
    into a supplied `ArtifactStoreBackendRegistry`.
  - Raw `ArtifactStore` instances, current local-root `ArtifactStoreFactory`
    callables, plugin-owned registries, and arbitrary universal plugin objects
    are rejected as backend plugin targets.
- Capability and preflight tests:
  - Capabilities distinguish supported, unsupported, and unknown for read,
    write, list, delete, checksum verification, commit/consistency, lookup,
    and materialization-related operations.
  - Selected remote writes fail closed on missing, unknown, or unsupported
    required capabilities.
  - Stage 14 metadata checks and import-only diagnostics do not satisfy Stage
    15 backend availability, capability admission, URI/config validation, or
    run-readiness checks.
  - Default checks do not perform network, credential, checksum, payload, or
    service-SDK probes.
- Catalog, bundle, and Stage 12 exchange tests:
  - Run catalog projections preserve external/published/location summaries as
    metadata-only records with redacted display fields.
  - Bundle/export/import manifests preserve Stage 15 summaries without
    materializing payloads or mutating authority state.
  - Stage 12 portable-run exchange rework maps any current opaque external-ref
    extension fields to Stage 15 summaries and records unsupported
    materialization diagnostics.
- Example fixture tests and documentation checks:
  - MLflow-like and object-store-style examples both use the same descriptor,
    registry, store ref, capability, lookup, redaction, unsupported-operation,
    and summary contracts.
  - Default tests use fake handlers/backends only. No MLflow, cloud SDK,
    container, network, credential, or external service dependency is allowed.
  - Documentation labels examples as design fixtures and contract fixtures, not
    first-party adapters.

Validation gate status:

- Confirmed. Implementation-plan drafting should translate this strategy into
  suite-level obligations per phase. Stage 12/14 APIs were rechecked for this
  handoff; phase planners must recheck current source again before code
  changes.

## Phase Shaping

Candidate phase boundaries:

- Phase 1 candidate: external artifact records and compatibility contracts.
  - Scope: `ArtifactLocationKind`, `ArtifactLocationSummary`,
    `ArtifactStoreRef`/config summary, `ExternalArtifactDeclaration`,
    `PublishedArtifactRecord`, immutable lookup request/result records, redaction
    helpers, strict plain-data serialization, and the adjacent-record-first
    `ArtifactRef` compatibility strategy.
  - Acceptance focus: old `ArtifactRef` round trips remain compatible; new
    summaries provide typed external, published, and multi-location semantics;
    secret-bearing fields are rejected; examples can be represented without
    backend SDKs.
  - Out of scope: backend registry, plugin loading, preflight integration,
    catalog/bundle rewrites, payload materialization, and real adapters.
- Phase 2 candidate: backend descriptor/factory, handler registry,
  capabilities, and fake backends.
  - Scope: store-owned descriptor/factory contract with contract/API versioning,
    normalized handler protocol, explicit backend registry, operation-specific
    capability records, config validation/redaction hooks, fake MLflow-like and
    object-store-style handlers, duplicate/missing diagnostics, and
    programmatic registration. A supplied-registry plugin adapter may be
    included once the registry contract exists, but it must use Stage 14
    generic discovery primitives explicitly and must not make metadata checks
    claim backend availability.
  - Acceptance focus: Stage 14-style adapter tests can normalize a loaded fake
    descriptor/factory into a supplied registry, but raw `ArtifactStore`
    objects, local-root factories, universal plugin objects, and plugin-owned
    registries are rejected.
  - Out of scope: changing Stage 14 CLI/preflight listing-only diagnostics
    into backend availability checks, automatic plugin loading, remote SDKs,
    network probes, payload upload/download, and execution-run store
    replacement beyond explicit fake contracts.
- Phase 3 candidate: external immutable input and published immutable output
  semantics.
  - Scope: declaration/registration behavior for external immutable inputs,
    published immutable output records, explicit immutable lookup by
    project-supplied key and validation policy, compatibility/incompatibility
    results, and unsupported-operation diagnostics.
  - Acceptance focus: lookup is explicit and does not become automatic global
    cache reuse; selected remote write/publish paths fail closed when required
    capabilities are unknown or unsupported; metadata-only workflows remain
    available.
  - Out of scope: planner-driven partial stage reuse, automatic cache lookup,
    payload publish/upload/download, retention deletion, and domain-specific
    artifact schemas.
- Phase 4 candidate: backend preflight, run catalog, and bundle metadata
  preservation.
  - Scope: Stage 15 backend availability/check IDs separate from Stage 14
    plugin metadata checks, URI/config validation, capability admission,
    selected write fail-closed checks, run catalog projections, bundle/export
    metadata preservation, and unsupported materialization diagnostics.
  - Acceptance focus: Stage 14 metadata/import checks never satisfy Stage 15
    backend availability or run-readiness; default checks avoid network,
    credential, checksum, payload, and SDK probes; catalogs and bundles preserve
    summaries with redaction.
  - Out of scope: standalone testing plan unless implementation-plan quality
    gate finds embedded suite obligations too large, Stage 16 materialization,
    remote payload export/import, and authority mutation.
- Phase 5 candidate: Stage 12 portable-run exchange rework.
  - Scope: recheck landed Stage 12 records and replace opaque external-ref
    extension fields with Stage 15 external/published/location summaries where
    appropriate, preserving metadata-only exchange and unsupported
    materialization diagnostics.
  - Acceptance focus: portable-run export/import round trips preserve external
    artifact facts without downloads, credential checks, payload access, or
    backend-specific permanent schemas.
  - Out of scope: changing Stage 12 authority semantics, adding materialization,
    requiring remote access during exchange, or locking provider-specific
    schemas into the core exchange format.
- Phase 6 candidate: examples, docs, and validation hardening.
  - Scope: MLflow-like and object-store-style design fixtures, adapter author
    guidance, validation matrix coverage, import-boundary tests, contract tests,
    and documentation that distinguishes fake design pressure tests from real
    first-party adapters.
  - Acceptance focus: both examples use the same generic contracts and expose
    no optional dependencies; implementation evidence is easy to review before
    Stage 16 materialization work begins.
  - Out of scope: real MLflow/S3/GCS/Azure/DVC/HTTP adapter implementations,
    cloud credentials, service containers, or opt-in integration suites.

Reviewability notes:

- Confirmed. These phase candidates are implementation-plan input, not final
  phase execution plans. Implementation-plan drafting may merge or split them
  for reviewability, but it must preserve the Stage 14 metadata-only boundary,
  Stage 12 metadata-only rework boundary, Stage 16 payload-materialization
  boundary, and fake-backend-first validation obligations.

## Implementation Readiness

Readiness checklist:

- Roadmap framing confirmed: yes
- Intent confirmed: yes
- Functionality and behavior confirmed: yes
- Design agreement confirmed: yes
- Design-safety review completed: yes, original review, renewed Stage 14
  alignment review, and latest targeted artifact-store backend pass all passed
  with required planning revisions
- Examples and validation strategy confirmed: yes
- Phase shaping confirmed: yes
- Open design-safety blockers resolved or accepted: yes
- Implementation-plan drafting prerequisites recorded: yes, recheck landed
  Stage 12 portable-run exchange records and Stage 14 plugin artifacts was
  completed for this handoff
- Ready for implementation-plan draft: yes; draft created and locally
  quality-gated

Open questions:

- None from design-safety review, renewed Stage 14 alignment review, or latest
  targeted artifact-store backend pass.
- None from examples/validation or phase shaping.

Handoff notes:

- This planning artifact has been converted into
  `docs/roadmap/stage-15/implementation-plan.md`.
- The implementation plan used this artifact as the primary source and used the
  completed Stage 12/14 source/API rechecks recorded above.
- Do not create phase execution plans until Phase 1 is selected and its phase
  execution plan is drafted.
