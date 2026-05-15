# Implementation Plan v15: External Artifact Interface Contract

## Metadata

- Status: Phase 5 merged; ready for Phase 6 execution planning
- Roadmap stage: `v15`
- Source planning notes:
  `docs/roadmap/stage-15/planning.md`
- Workflow: `.codex/workflows/roadmap-stage-implementation.md`
- Related implementation plans:
  - `docs/roadmap/stage-14/implementation-plan.md`
  - `docs/roadmap/stage-12/implementation-plan.md`
  - `docs/roadmap/stage-13/implementation-plan.md`
  - `docs/roadmap.md`
- Related source docs:
  - `docs/structure.md`
  - `docs/GLOSSARY.md`
  - `docs/features/remote-stores.md`
  - `docs/features/artifacts.md`
  - `docs/features/plugins.md`
  - `docs/features/preflight.md`
  - `docs/features/run-catalog.md`
  - `docs/features/io.md`
  - `docs/features/reliability.md`
  - `docs/features/testing.md`
- Draft pass: complete on 2026-05-15 from confirmed Stage 15 planning notes
  after Stage 14 implementation completion
- Refine pass: complete on 2026-05-15 after local plan-quality review
- Plan quality gate: passed on 2026-05-15 after local
  review/refinement/confirmation
- Current phase: ready for Phase 6 execution planning
- Blockers:
  - No roadmap-stage planning blocker remains.
  - No plan-quality blocker remains.
  - No Phase 6 execution plan exists yet; do not start Phase 6 product
    implementation until Phase 6 execution planning is complete.

## Summary

- Goal: implement backend-neutral external artifact records, artifact-store
  backend descriptor/handler/capability contracts, fake backends, immutable
  input/output semantics, preflight/catalog/bundle preservation, and Stage 12
  portable-run exchange metadata rework.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-15/planning.md`.
- Approved behavior: metadata-first external refs; adjacent artifact summaries
  by default; operation-specific supported/unsupported/unknown capabilities;
  cheap default preflight; selected remote writes fail closed; explicit
  immutable lookup only; no real backends; no payload materialization.
- Source behavior confirmation: complete in the planning artifact.
- Key design constraints: keep `loom` domain-neutral, dependency-light,
  import-safe, fake-backend-first, and plain-data serializable; keep plugin
  discovery explicit; keep Stage 14 metadata checks separate from Stage 15
  backend availability; keep Stage 12 rework metadata-only.
- Source design-safety evidence: passed original design-safety review, renewed
  Stage 14 alignment review, latest targeted artifact-store backend review,
  and post-Stage 14 implementation alignment review.
- Future-roadmap impact: Stage 16 materialization, Stage 17/18 container/HPC
  staging decisions, Stage 19 reliability, and Stage 20 cleanup/retention
  consume Stage 15 records without forcing Stage 15 to implement payload
  movement or real cloud/tracking adapters.
- Reusable interface, adapter, or protocol assumptions: artifact identity and
  location summaries are broadly reusable; backend descriptors/factories
  normalize into a store-owned registry; plugin adapters are explicit and
  supplied-registry-based; run exchange consumes stable summaries.
- Examples covered: MLflow-like tracking-system and object-store-style fake
  adapter fixtures using the same generic contracts.
- Source phase shaping: six phases confirmed in the planning artifact.
- Out of scope: first-party MLflow, DVC, HTTP, S3, GCS, Azure, or cloud
  backends; upload/download/materialization; credential refresh/storage;
  automatic global cache lookup; partial stage reuse; domain-specific artifact
  schemas.

## Goal

Implement v15 as Loom's external artifact interface contract. The stage should
make external immutable inputs, published immutable outputs, multi-location
artifact facts, backend capabilities, backend registry/handler contracts,
preflight diagnostics, and metadata-only run-exchange preservation stable
without requiring payload availability or optional service dependencies.

When complete, adapter authors can target a generic artifact-store backend
descriptor/factory contract, project code can declare or inspect external
artifact facts safely, run catalogs and bundles can preserve those facts as
metadata, and later stages can add explicit payload movement on top of the
same contracts.

## Context

The repository already has the foundations v15 should preserve:

- `ArtifactRef` is a compact strict record in `src/loom/artifacts.py`. It
  rejects unknown top-level fields and already carries URI, type, codec,
  checksum, fingerprint, producer stage, timestamp, and plain metadata.
- `ArtifactStore` in `src/loom/pipeline/stores/artifact_store.py` is a
  run/local-operation protocol with `save`, `register`, `load`, `exists`,
  `verify_checksum`, and `validate`.
- `LocalArtifactStore` is the current reference implementation and accepts
  local/file URIs only, with explicit external-local registration policy.
- Authority capability records exist under `loom.pipeline.stores`, but they
  describe authority lifecycle/store support, not artifact-store backend
  operation support.
- Preflight has a stable artifact check ID, `artifact_store.available`, and
  Stage 14 added optional plugin checks, `plugins.metadata` and
  `plugins.load`, with explicit selectors.
- Stage 14 is complete. `loom.plugins` exports
  `LOOM_ARTIFACT_STORE_BACKENDS_GROUP = "loom.artifact_store_backends"`,
  `PluginRecord`, `list_entry_points`, `load_entry_points`, diagnostic
  summaries, and readiness metadata. `LOADABLE_PLUGIN_GROUPS` contains only
  recipes and codecs; artifact-store backends remain listing-only in generic
  CLI/preflight diagnostics.
- Stage 12 has concrete portable-run exchange and local bundle records:
  `RunBundleManifest`, `PortableRunExportRecord`,
  `PortableRunImportRecord`, `RunExporter`, `RunImporter`, exchange result
  envelopes, payload selections, diagnostics, and `extensions` fields.

Implementation-plan source recheck on 2026-05-15 found no artifact-store
backend descriptor, backend registry, backend capability model, external
artifact summary, published artifact lookup contract, or backend availability
preflight checks in source. This plan therefore defines those contracts here
and treats Stage 14 plugin metadata and Stage 12 extension fields as inputs,
not as finished backend semantics.

## Planning Readiness

- Source planning notes:
  `docs/roadmap/stage-15/planning.md`
- Functionality and behavior baseline:
  complete. The notes lock backend-neutral records, Stage 14-compatible
  backend descriptor/factory contracts, fake handlers, external immutable
  declarations, published immutable lookup, multi-location summaries,
  preflight, catalog/bundle preservation, Stage 12 metadata rework, and two
  compatibility examples.
- Design-safety review:
  passed with required planning revisions. Renewed Stage 14 and targeted
  artifact-store backend reviews also passed.
- Post-Stage 14 implementation alignment review:
  passed. The planning artifact now uses landed Stage 14 public APIs and keeps
  artifact-store backend plugin entries listing-only for generic
  CLI/preflight diagnostics.
- Stage 12 source/API recheck:
  complete. Phase 5 should consume current run-exchange records and extension
  fields unless a narrow schema revision is proven necessary.
- Examples and validation strategy:
  complete. Validation is fake-backend-first and excludes MLflow/cloud SDKs,
  network, credentials, containers, and external services.
- Phase shaping:
  complete; six implementation phases are recorded below.
- Implementation readiness blockers from planning:
  none after the post-Stage 14 implementation alignment review.
- Accepted risks and revisit triggers:
  Stage 14 plugin diagnostics still classify artifact-store backends as
  listing-only; adjacent records may require callers to carry both
  `ArtifactRef` and summaries; Stage 12 may need a narrow schema revision if
  extension fields cannot carry summaries clearly; capability records may
  overlap authority capability style.

## Desired Outcome

When all phases are complete:

- Public artifact records describe location kind, store references, external
  immutable declarations, published immutable records, validation policies,
  lookup requests/results, and redacted summaries as strict plain data.
- Existing `ArtifactRef` round trips remain compatible. A top-level
  `ArtifactRef` schema revision is added only if Phase 1 proves adjacent
  records cannot provide required validation or unambiguous persistence.
- Store-owned backend contracts exist for descriptor/factory versioning,
  backend kind/key policy, config validation/redaction, capability reporting,
  run-context handoff, fake handlers, duplicate/missing diagnostics, and
  structured unsupported operation results.
- Programmatic backend registry registration is first-class. Any plugin
  adapter is explicit, uses landed Stage 14 generic entry point primitives, and
  registers into a caller-supplied `ArtifactStoreBackendRegistry`.
- Stage 14 plugin metadata/list/import checks remain distinct from Stage 15
  backend availability, configured capability admission, and run-readiness.
- External immutable inputs and published immutable outputs can be registered,
  inspected, summarized, and looked up explicitly without downloads.
- Selected remote write/publish paths fail closed when required backend
  capabilities are missing, unsupported, or unknown.
- Preflight exposes stable backend/config/capability checks that are cheap by
  default; network, credential, checksum, and payload probes remain opt-in.
- Run catalogs, local bundles, and portable-run exchange preserve external,
  published, and location summaries as metadata-only records with redaction and
  unsupported-materialization diagnostics.
- MLflow-like and object-store-style fake examples demonstrate that both
  tracking-system indirection and object-addressed storage fit the same
  generic contracts.

## Non-Goals

- No first-party MLflow, DVC, W&B, HTTP, S3, GCS, Azure, cloud, or tracking
  backend implementation.
- No optional backend SDK, service client, credential manager, or network
  dependency in core.
- No upload, download, publish transfer, implicit bundle materialization,
  remote payload import/export, cache fill, or remote deletion behavior.
- No automatic global cache lookup, planner-owned partial stage reuse, or
  domain-specific checkpoint continuation.
- No plugin discovery or backend target loading during `import loom`, CLI
  help, default preflight, or unrelated commands.
- No raw `ArtifactStore` instance, current local-root `ArtifactStoreFactory`,
  plugin-owned registry, or universal plugin object protocol as a backend
  plugin contract.
- No authority mutation as part of metadata-only bundle/catalog preservation.

## Constraints

- Keep `loom` domain-neutral and follow `docs/structure.md` boundaries.
- Use `docs/GLOSSARY.md` vocabulary consistently.
- Do not introduce heavyweight runtime dependencies.
- Treat authored config as trusted project code while keeping persisted
  metadata redacted and shareable.
- Keep `loom.artifacts` import-light. It must not import stores, diagnostics,
  plugins, runs, CLI, or optional backend packages.
- Keep store contracts under `loom.pipeline.stores`. Stores may import public
  artifact records and neutral URI helpers, but must not import run-exchange
  internals or plugin discovery at import time.
- Keep `loom.plugins` as explicit discovery/loading coordination. Store
  registries own backend semantics.
- Keep `loom.runs` as the consumer of artifact summaries for portable-run
  exchange; stores do not import bundle/export/import code.
- Run `make validate-pr` and `make test-summary` before each phase PR is
  prepared, or record why either command could not run.

## Design Principles

- **Metadata first.** External/published refs must remain inspectable without
  credentials, network access, optional SDKs, or local payload availability.
- **Compatibility before schema ambition.** Preserve existing `ArtifactRef`
  semantics unless a narrow versioned revision gives concrete guarantees that
  adjacent summaries cannot.
- **Store ownership.** Backend descriptors, handlers, capabilities, and
  registries are store contracts. Plugin discovery only loads selected objects
  into supplied registries.
- **Fail closed for selected operations.** Unknown or unsupported required
  capabilities cannot satisfy selected remote write/publish paths.
- **Cheap by default.** Preflight defaults to config/registry/URI/capability
  checks. Network, credential, checksum, and payload probes are opt-in.
- **Plain summaries.** Catalogs, bundle manifests, preflight details, and docs
  must not serialize loaded Python objects, credentials, SDK clients, or unsafe
  exception data.
- **Future behavior as explicit records.** Stage 15 may shape unsupported
  operation results, staging/cache descriptors, and consistency hints for
  Stage 16/19/20, but must not hide payload movement, retries, or cleanup.

## Key Design Choices

- Add external/published/location value objects around `ArtifactRef` rather
  than making every artifact ref remote-aware by default.
- Permit a minimal versioned `ArtifactRef` revision only if Phase 1 proves that
  adjacent summaries cannot enforce location kind, validation policy, or
  compatibility-safe persistence.
- Keep initial artifact records in or exported through `loom.artifacts`. If
  `src/loom/artifacts.py` becomes too large, a phase may add an adjacent
  import-light module and re-export from `loom.artifacts`; do not convert the
  module to a package unless a phase plan records a concrete import reason.
- Add backend contracts under new focused modules in `loom.pipeline.stores`,
  re-exporting public types from `loom.pipeline.stores` only where consistent
  with existing store exports.
- Use operation-specific capability support records with
  supported/unsupported/unknown states instead of bare booleans or
  scheme-based assumptions.
- Define backend descriptors/factories with contract/API versioning, backend
  kind/key normalization, supported URI schemes, config validation/redaction,
  capability reporting, cheap preflight hooks, and run-context construction
  handoff.
- Keep backend registry registration programmatic first. A plugin adapter may
  be added as a lazy supplied-registry adapter, but generic Stage 14
  CLI/preflight plugin checks remain listing-only for artifact-store backends.
- Keep Stage 12 exchange rework metadata-only, using existing extension fields
  where clear enough and adding a narrow versioned schema field only if needed
  for unambiguous summaries.
- Use MLflow-like and object-store-style examples as fake design fixtures, not
  as first-party adapters or dependencies.

## Conflicts And Tradeoffs

- **Adjacent records vs. a broader `ArtifactRef`:** adjacent records preserve
  persisted compatibility, but they require callers to keep related summaries
  together. Phase 1 must prove summary projection and validation are clear.
- **Programmatic backend registry vs. plugin ergonomics:** programmatic
  registration is more explicit, but avoids letting discovery own store
  semantics. A supplied-registry plugin adapter can restore ergonomics without
  auto-loading.
- **Listing-only Stage 14 diagnostics vs. new backend adapter:** keeping
  generic plugin diagnostics listing-only avoids false readiness, but adapter
  authors still need an explicit loading path. The plan permits a specialized
  adapter while keeping CLI/preflight metadata separate from backend
  availability.
- **Stage 12 extensions vs. schema widening:** extension fields are available
  now, but durable summaries may deserve a narrow schema field if extension
  placement becomes ambiguous. Phase 5 must record the decision.
- **Capability breadth vs. maintainability:** operation-specific capabilities
  add records, but prevent scattered assumptions and preserve future Stage 16
  materialization flexibility.

## Maintainability Assessment

The design is maintainable if ownership boundaries stay narrow:

- `loom.artifacts` owns shareable identity/location records.
- `loom.pipeline.stores` owns backend behavior, descriptors, registry,
  capabilities, fake handlers, and backend diagnostics.
- `loom.plugins` owns entry point discovery and explicit selected loading only.
- `loom.diagnostics` owns preflight presentation over public store contracts.
- `loom.runs` owns portable-run exchange and bundle/catalog preservation over
  public artifact summaries.

The largest maintainability risk is implying backend availability from plugin
metadata. The phases must keep `plugins.metadata`/`plugins.load` diagnostics
separate from backend availability and capability checks.

## Extensibility Assessment

The reusable extension pattern is:

1. Describe external/published/location facts as strict plain records.
2. Register backend descriptor/factory objects into a store-owned registry.
3. Normalize backend-specific config into redacted store refs and capabilities.
4. Use handlers for metadata validation, cheap checks, lookup, and structured
   unsupported operation results.
5. Let later materialization stages implement payload movement behind the same
   handler/capability contract.

This pattern is generic enough for MLflow-like tracking systems,
object-store-style backends, HTTP/read-only refs, local published directories,
and project-specific adapters without adding those services to core.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Artifact-store plugin diagnostics remain listing-only in generic Stage 14 CLI/preflight output | Prevents metadata checks from implying backend availability or run-readiness | A config-aware Stage 15 backend adapter/check path exists and wording can distinguish descriptor-load success from run-readiness |
| Adjacent artifact summaries may require two-record coordination with `ArtifactRef` | Preserves persisted ref compatibility | Phase 1 proves validation/persistence is ambiguous without a narrow `ArtifactRef` revision |
| Stage 12 exchange may need a schema revision instead of only extensions | Current source offers extension points, but durable summaries may need explicit placement | Phase 5 cannot represent summaries clearly in existing extension fields |
| Capability records may overlap authority capability style | Artifact-store support states need unknown/unsupported/supported semantics for artifact operations | Shared helpers can be extracted without coupling stores to authority or losing unknown support |
| Fake examples shape adapter expectations before real adapters exist | They are needed to pressure-test genericity without dependencies | First real optional adapter exposes missing core fields or overfitted example semantics |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by managing Codex local review using
  `.codex/prompts/implementation-plan-review.md` criteria. No separate
  reviewer subagent was used because this turn did not request delegated agent
  work.
- Refinement pass: used to update planning for completed Stage 14, record
  Stage 12/14 source rechecks, and tighten plugin/backend-readiness boundaries.
- Confirmation review: complete; no blocking findings remain.
- Budget status: review used, refinement used, confirmation used.
- Automatic merge mode: enabled
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Default phase base/target: `develop`; each phase execution planner must
  recompute and record the actual stack predecessor and PR target before
  creating its worktree.
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Workflow path: expanded path is expected for every phase because the stage
  creates public records/protocols and crosses artifacts, stores, diagnostics,
  plugins, and run exchange.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `external-artifact-records` | merged | `codex/external-artifact-records` | https://github.com/samcantrill/loom/pull/160 | `loom.artifacts`, artifact package tests | Add external/published/location records and `ArtifactRef` compatibility contracts | Artifact/package/contract tests plus full PR gate | Old `ArtifactRef`, external declaration, published record, location summary |
| 2 | `artifact-store-backend-contracts` | merged | `codex/artifact-store-backend-contracts` | https://github.com/samcantrill/loom/pull/161 | `loom.pipeline.stores`, optional lazy plugin adapter | Add backend descriptor/factory, registry, capabilities, fake handlers, and supplied-registry plugin adapter boundary | Store/plugin contract tests plus full PR gate | MLflow-like fake descriptor, object-store-style fake descriptor |
| 3 | `immutable-artifact-semantics` | merged | `codex/immutable-artifact-semantics` | https://github.com/samcantrill/loom/pull/162 | artifact/store registration and lookup APIs | Add external immutable input and published immutable output registration/lookup semantics | Unit/contract tests plus full PR gate | Explicit compatible/incompatible/missing/unsupported lookup |
| 4 | `backend-preflight-catalog-bundles` | merged | `codex/backend-preflight-catalog-bundles` | https://github.com/samcantrill/loom/pull/163 | diagnostics, catalog projections, bundle metadata preservation | Add backend/config/capability checks and metadata-only catalog/bundle preservation | Diagnostics/run-catalog/bundle tests plus full PR gate | Missing handler, unsupported write, redacted summaries |
| 5 | `stage-12-exchange-rework` | merged | `codex/stage-12-exchange-rework` | https://github.com/samcantrill/loom/pull/164 | `loom.runs` portable-run exchange | Rework Stage 12 exchange/export/import metadata to consume Stage 15 summaries | Run exchange/import/export tests plus full PR gate | Metadata-only external refs round trip through exchange |
| 6 | `external-artifact-docs-validation` | pending | TBD | TBD | docs, examples, cross-cutting tests | Add examples, docs, validation matrix, import-boundary hardening | Full validation and test summary | MLflow-like and object-store-style fake examples |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Plan quality gate | Implementation workflow | Local review, one refinement pass, and confirmation review completed on 2026-05-15 before Phase 1 starts | resolved |

## Plan Quality Gate

- Status: passed
- Gate date: 2026-05-15
- Reviewer: managing Codex local review using the
  `.codex/prompts/implementation-plan-review.md` criteria. No separate
  reviewer subagent was used because this turn did not request delegated agent
  work.
- Review pass: complete; planning readiness, maintainability, extensibility,
  conflicting design choices, technical debt, test strategy, reviewability, and
  future-roadmap compatibility were checked.
- Refinement pass: used; the planning artifact and this implementation plan
  now reflect completed Stage 14 implementation, landed plugin readiness APIs,
  current Stage 12 exchange source APIs, supplied-registry backend adapter
  boundaries, and phase-specific validation obligations.
- Confirmation review: complete; no blocking findings remain after the
  refinement.
- Budget status: review used, refinement used, confirmation used.
- Planning-readiness dependencies:
  - `docs/roadmap/stage-15/planning.md` records completed examples,
    validation strategy, phase shaping, design-safety reviews, and
    implementation readiness.
  - Stage 14 implementation is complete and has been rechecked.
  - Stage 12 run-exchange source APIs have been rechecked.
  - No unresolved `blocked` or `needs discussion` planning decisions remain.
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
| Concern | Planning metadata and source evidence | The planning artifact still described Stage 14 as not implemented, which would let phase planners treat plugin APIs as uncertain. | Updated planning and this plan to reference the completed Stage 14 implementation plan and landed `loom.plugins` API. |
| Concern | Plugin/backend boundary | Stage 14 exposes generic `load_entry_points(...)`, but generic plugin diagnostics still keep artifact-store backends listing-only. A phase could accidentally conflate target import with backend availability. | Recorded that Stage 15 may add a supplied-registry adapter, but backend availability/capability checks are separate Stage 15 diagnostics and generic Stage 14 CLI/preflight metadata remains listing-only. |
| Concern | Stage 12 exchange handoff | Stage 12 records use strict schemas plus extension fields. A broad Stage 15 rewrite could either leave summaries opaque or over-widen bundle schemas. | Phase 5 must recheck current `src/loom/runs` and either use extension fields clearly or record a narrow schema revision with compatibility tests. |
| Note | Phase reviewability | The original phase candidates were correct but broad. | Kept six phases and made each phase explicitly own design impact, future compatibility, and validation obligations. |

## Phase 1: External Artifact Records And Compatibility Contracts

Status: merged
Slug: `external-artifact-records`
Branch: `codex/external-artifact-records`
Worktree: `/home/samcantrill/work/loom-worktrees/external-artifact-records`
PR: https://github.com/samcantrill/loom/pull/160
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public persisted
artifact records and compatibility contracts

### Scope

- Goal: add strict, backend-neutral artifact value objects for external,
  published, and multi-location semantics while preserving existing
  `ArtifactRef` behavior.
- Files/modules owned:
  - `src/loom/artifacts.py` and, only if needed for maintainability, an
    import-light adjacent artifact-record module re-exported through
    `loom.artifacts`
  - package export tests under `tests/package`
  - artifact unit tests under `tests/unit/loom`
  - contract tests under `tests/contracts`
- Behavior implemented:
  - `ArtifactLocationKind` for managed, external immutable, published
    immutable, staging, cache, and materialized location meanings.
  - `ArtifactLocationSummary` with authority/derived distinction, URI or
    redacted display URI, store kind/ref facts, checksum/fingerprint facts,
    size when known, and namespaced backend details.
  - `ArtifactStoreRef` or equivalent backend-neutral store reference/config
    summary with kind/key, root/URI, redacted display fields, and plain
    backend-owned details.
  - `ExternalArtifactDeclaration` for authored or resolved external immutable
    input facts.
  - `PublishedArtifactRecord` for immutable output identity, producer
    provenance, reuse key, validation policy, owner/retention hints, and
    evidence.
  - `ImmutableArtifactLookupRequest` and `ImmutableArtifactLookupResult` for
    explicit lookup outcomes: compatible, incompatible, missing, unsupported.
  - Stable to/from summary helpers and strict unknown-field handling.
  - Compatibility tests proving old `ArtifactRef` dictionaries still load.
- Decisions applied: DAQ-1, DAQ-2, DAQ-5, DAQ-8, DAQ-9, DAQ-10.
- Examples or docs covered: old local artifact ref, external immutable input,
  published immutable output, cache/staging derived location, redaction.
- Out of scope:
  - Backend registry or handler behavior.
  - Plugin loading or backend descriptors.
  - Preflight integration.
  - Catalog, bundle, or Stage 12 rewrites.
  - Payload materialization or real adapters.

### Tasks

- Define the public record names and serialization schemas.
- Add validation for required fields, unknown fields, supportable enum values,
  digest fields, plain-data metadata, and redacted display values.
- Add namespaced backend detail validation that keeps core behavior independent
  from backend-specific fields.
- Add summary projection helpers that can be embedded into artifact metadata,
  catalog rows, and run-exchange records.
- Decide whether adjacent records provide enough guarantees. Add a minimal
  `ArtifactRef` schema revision only if the phase plan records the concrete
  missing guarantee and compatibility strategy.
- Add package/import-boundary tests proving `loom.artifacts` remains
  import-light.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom tests/contracts tests/package` | Target artifact records, old `ArtifactRef` compatibility, package exports, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: old `ArtifactRef` dictionaries round trip; new records
  reject ambiguous or secret-bearing core fields; summaries serialize to strict
  plain data.
- Design-decision evidence: adjacent-record-first strategy is either proven or
  a narrow `ArtifactRef` revision is recorded with concrete justification.
- Future-roadmap compatibility evidence: location kinds distinguish
  authoritative vs derived cache/staging/materialized facts without implying
  payload availability.
- Interface, adapter, or protocol reuse evidence: records are usable by stores,
  diagnostics, run catalog, and exchange without importing backends.
- Documentation evidence: docstrings or feature docs explain external vs
  published vs derived locations.
- Domain-neutrality evidence: no service-specific fields are required by core.

### Design Impact

This phase creates persisted/public value objects. The phase execution plan
must record exact field names, schema version policy, unknown-field policy, and
how summaries compose with existing `ArtifactRef`.

### Future Compatibility

Stage 16 materialization and Stage 20 cleanup consume these location summaries.
The phase must avoid making cache/staging records authoritative.

### Alternatives Rejected

- Putting all semantics into untyped `ArtifactRef.metadata`.
- Broadly expanding every `ArtifactRef` with external/published fields before
  adjacent summaries are proven insufficient.
- Service-specific MLflow/object-store fields as core schema.

### Debt Introduced

Potential two-record coordination between `ArtifactRef` and location
summaries. Revisit only if implementation or tests show callers cannot enforce
location semantics.

### Reviewability

Keep the diff focused on records, validation, serialization, and tests. Do not
include store registry or preflight work in this phase.

### Merge Metadata

- Merged: 2026-05-15 via squash merge to `develop`
- Merge commit: `be05f6e9b71f4bcd2b6372df2c6d16f9009ac48b`
- PR: https://github.com/samcantrill/loom/pull/160
- Implementation summary: added strict backend-neutral artifact records in
  `loom.artifacts`, including location kinds, generic store refs, location
  summaries, external declarations, published records, and immutable lookup
  request/result records; preserved `ArtifactRef` top-level compatibility and
  kept backend/plugin/preflight/catalog/bundle behavior out of scope.
- Checks:
  - Focused Phase 1 pytest paths passed: 88 passed in 14.72s.
  - `make validate-pr` passed outside the sandbox: Ruff passed, Pyright passed
    with 0 errors, default harness passed, config-extra harness passed, and
    build passed.
  - `make test-summary` passed: overall 2090 passed / 18 skipped / 1675
    deselected.
  - GitHub checks were unavailable; `gh pr checks 160 --watch=false` reported
    no checks on the branch.
- Automated review: managing agent local review approved with no blocking or
  non-blocking findings.
- Follow-up notes: remote phase branch cleanup and worktree removal are safe
  because no successor branch depends on Phase 1.

## Phase 2: Artifact-Store Backend Contracts

Status: merged
Slug: `artifact-store-backend-contracts`
Branch: `codex/artifact-store-backend-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/artifact-store-backend-contracts`
PR: https://github.com/samcantrill/loom/pull/161
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public backend
contracts and an extension-point boundary

### Scope

- Goal: add store-owned backend descriptor/factory, handler, registry,
  capability, fake-backend, operation-result, and optional supplied-registry
  plugin adapter contracts.
- Files/modules owned:
  - new focused modules under `src/loom/pipeline/stores`
  - `src/loom/pipeline/stores/__init__.py` exports
  - optional lazy adapter module under `src/loom/plugins`
  - store/plugin/unit/contract tests
- Behavior implemented:
  - Backend descriptor/factory contract with contract/API version, backend
    kind/key, supported URI schemes, config validation/redaction, capability
    provider, cheap check hooks, and run-context handoff.
  - Normalized backend handler protocol for metadata validation, redaction,
    capability reporting, lookup/check operations, and structured unsupported
    results for out-of-stage payload operations.
  - `ArtifactStoreBackendRegistry` keyed by backend kind with deterministic
    duplicate/missing diagnostics and programmatic registration.
  - Operation-specific `ArtifactStoreCapabilities` support records for read,
    write, list, delete, checksum verification, commit/consistency, lookup,
    publish/materialize support, and unknown support.
  - Fake MLflow-like and object-store-style handlers/descriptors for contract
    tests only.
  - Optional explicit `load_artifact_store_backend_entry_points(...)` adapter
    that uses Stage 14 generic entry point primitives and registers normalized
    descriptors/factories into a supplied registry.
- Decisions applied: DAQ-2, DAQ-3, DAQ-4, DAQ-6, DAQ-8, DAQ-10.
- Examples or docs covered: fake tracking descriptor, fake object-store
  descriptor, duplicate backend kind, missing handler, incompatible contract
  version.
- Out of scope:
  - Changing generic Stage 14 CLI/preflight plugin checks to claim backend
    availability.
  - Automatic plugin discovery/loading.
  - Real backend SDKs, network probes, credentials, upload/download, or store
    replacement in runner lifecycle.

### Tasks

- Define descriptor/factory and handler protocols with runtime-checkable
  shapes only where useful.
- Add version compatibility helpers for backend contract/API version.
- Add backend kind/key normalization and duplicate handling.
- Add backend config/ref validation and redaction hooks.
- Add capability support-state records and admission helpers.
- Add structured backend diagnostics and unsupported operation results.
- Add fake descriptors/handlers for MLflow-like and object-store-style tests.
- Add supplied-registry plugin adapter only after registry contracts exist.
- Preserve Stage 14 generic plugin readiness wording unless a phase records a
  safe wording update that does not imply run-readiness.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/stores tests/unit/loom/plugins tests/contracts tests/package` | Target backend contracts, registry behavior, plugin adapter boundary, and exports | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: fake descriptors normalize into handlers; duplicate and
  missing handlers fail deterministically; unsupported operations return
  structured results.
- Design-decision evidence: raw `ArtifactStore`, local-root
  `ArtifactStoreFactory`, plugin-owned registries, and universal plugin objects
  are rejected.
- Future-roadmap compatibility evidence: capabilities leave Stage 16
  materialization and Stage 19 retry/cleanup free to build later.
- Interface, adapter, or protocol reuse evidence: programmatic registration
  works without plugins; plugin adapter is supplied-registry-based.
- Documentation evidence: public docs distinguish descriptor-load success from
  backend availability/run-readiness.
- Domain-neutrality evidence: fake handlers use no real service package or
  domain model.

### Design Impact

This phase defines the core extension point. The phase execution plan must lock
the minimal descriptor/factory/handler surface and version compatibility policy
before code changes.

### Future Compatibility

Optional backend packages should be able to adapt to the contract without
future core refactors. Keep service-client lifetimes outside serialized core
records.

### Alternatives Rejected

- Treating raw `ArtifactStore` instances as plugin targets.
- Reusing the current local-root factory as the plugin contract.
- Making `loom.plugins` own backend registry semantics.
- Updating generic `plugins.load` checks to imply run-readiness.

### Debt Introduced

Generic Stage 14 readiness may still say artifact-store backends are
listing-only even after a specialized programmatic adapter exists. Revisit
only with wording that distinguishes descriptor-load success from configured
backend readiness.

### Reviewability

Keep runner integration minimal. This phase may define run-context handoff
records, but should not replace execution artifact-store wiring.

### Merge Metadata

- Merged: 2026-05-15 via squash merge to `develop`
- Merge commit: `0a87ad19755816b616ddadcc9713407e0ecf74a1`
- PR: https://github.com/samcantrill/loom/pull/161
- Implementation summary: added `loom.pipeline.stores.artifact_backends` with
  backend descriptor/factory/handler protocols, operation-specific
  capabilities, structured diagnostics/results, backend-kind normalization, and
  `ArtifactStoreBackendRegistry`; exported the public store contract names; and
  added lazy `loom.plugins.load_artifact_store_backend_entry_points(...)` for
  Stage 14 entry-point loading into caller-supplied registries while preserving
  generic artifact-store backend readiness as listing-only.
- Checks:
  - Focused Phase 2 pytest paths passed: 76 passed.
  - Broad Phase 2 pytest target passed outside the sandbox: 522 passed / 3
    skipped.
  - `make validate-pr` passed outside the sandbox: Ruff passed, Pyright passed
    with 0 errors, default harness passed with 1634 passed / 26 skipped / 18
    deselected, config-extra passed with 440 passed / 1671 deselected, and
    build passed.
  - `make test-summary` passed: overall 2102 passed / 18 skipped / 1687
    deselected.
  - GitHub CI `checks` job passed on the final PR head in 2m54s.
- Automated review: managing agent local review approved with no blocking or
  non-blocking findings; final pre-merge verification confirmed PR base
  `develop`, head `codex/artifact-store-backend-contracts`, successful CI, and
  Phase 2-scoped diff.
- Follow-up notes: branch/worktree cleanup is safe because no successor branch
  depends on Phase 2.

## Phase 3: Immutable Artifact Semantics

Status: merged
Slug: `immutable-artifact-semantics`
Branch: `codex/immutable-artifact-semantics`
Worktree: `/home/samcantrill/work/loom-worktrees/immutable-artifact-semantics`
PR: https://github.com/samcantrill/loom/pull/162
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase connects new public records to
store semantics and lookup behavior

### Scope

- Goal: implement external immutable input declaration/registration,
  published immutable output records, explicit lookup, validation policy, and
  fail-closed selected operation admission.
- Files/modules owned:
  - `src/loom/artifacts.py` or adjacent artifact record modules
  - `src/loom/pipeline/stores` backend helper modules
  - targeted artifact/store tests
- Behavior implemented:
  - External immutable declarations can be validated against store refs and
    handler capabilities without downloading payloads.
  - Published immutable output records carry reuse key, producer provenance,
    validation evidence, owner/retention hints, and unsupported-materialization
    diagnostics.
  - Immutable lookup requests return compatible, incompatible, missing, or
    unsupported results.
  - Selected remote write/publish paths fail closed when required capabilities
    are unsupported or unknown.
  - Metadata-only external/published summaries remain valid when no backend is
    configured for materialization.
- Decisions applied: DAQ-1, DAQ-4, DAQ-5, DAQ-6, DAQ-8, DAQ-9.
- Examples or docs covered: read-only external input, published immutable
  output with reuse key, incompatible checksum/fingerprint evidence, unknown
  write capability.
- Out of scope:
  - Automatic planner/global cache lookup.
  - Payload publish/upload/download.
  - Retention deletion or garbage collection.
  - Domain-specific artifact schemas.

### Tasks

- Add declaration/registration helpers over the records from Phase 1 and
  handlers from Phase 2.
- Add validation-policy helpers for type, schema, checksum, fingerprint, and
  project-supplied reuse key.
- Add explicit lookup helper APIs and result summaries.
- Add capability-admission helpers for selected read/write/publish/lookup
  operations.
- Add tests proving lookup does not run automatically from planner defaults.
- Add tests proving metadata-only flows do not require configured credentials
  or network access.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom tests/unit/loom/pipeline/stores tests/contracts` | Target immutable declaration, published records, lookup, and capability admission | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: explicit lookup outcomes are deterministic; selected
  writes fail closed on missing/unknown capabilities.
- Design-decision evidence: lookup is opt-in and does not become automatic
  planner cache reuse.
- Future-roadmap compatibility evidence: publish/materialize results are
  shaped but unsupported until Stage 16.
- Interface, adapter, or protocol reuse evidence: handlers can provide lookup
  without service-specific core fields.
- Documentation evidence: examples show external input and published output
  semantics without payload transfer.
- Domain-neutrality evidence: reuse keys are project-supplied generic strings,
  not domain schemas.

### Design Impact

This phase turns records into behavior. The phase execution plan must identify
which helper APIs are public and where planner handoff stops.

### Future Compatibility

Stage 16 can materialize compatible lookup results explicitly. Stage 20 can use
retention hints later without Stage 15 deleting anything.

### Alternatives Rejected

- Implicit cross-run artifact reuse.
- Treating URI scheme as capability proof.
- Requiring checksum or credential probes for metadata-only declarations.

### Debt Introduced

Some lookup result fields may be conservative until a real adapter is selected.
Revisit when first optional backend adapter lands.

### Reviewability

Do not touch run catalog or bundle code in this phase except via tests proving
records are serializable.

### Merge Metadata

- Merged: 2026-05-15 via squash merge to `develop`
- Merge commit: `f5816161edc819c9d052cf934dbfd609dcd3af10`
- PR: https://github.com/samcantrill/loom/pull/162
- Implementation summary: added `loom.pipeline.stores.immutable_artifacts`
  with metadata-only external declaration and published-record validation,
  fail-closed selected operation admission, explicit immutable lookup,
  validation-policy comparison, and `ArtifactRef` projection helpers; exported
  the public store helper names; and added unit, contract, and package
  coverage for explicit lookup and metadata-only semantics.
- Checks:
  - Focused Phase 3 pytest paths passed: 68 passed.
  - Broad Phase 3 pytest target passed outside the sandbox: 1376 passed / 10
    skipped.
  - `make validate-pr` passed outside the sandbox: Ruff passed, Pyright passed
    with 0 errors, default pytest passed, config-extra pytest passed, and build
    passed.
  - `make test-summary` passed: overall 2110 passed / 18 skipped / 1695
    deselected.
  - GitHub CI `checks` job passed on the final PR head in 2m44s.
- Automated review: managing agent local review approved with no blocking or
  non-blocking findings; final pre-merge verification confirmed PR base
  `develop`, head `codex/immutable-artifact-semantics`, successful CI, and
  Phase 3-scoped diff.
- Follow-up notes: branch/worktree cleanup is safe because no successor branch
  depends on Phase 3.

## Phase 4: Backend Preflight, Catalog, And Bundle Preservation

Status: merged
Slug: `backend-preflight-catalog-bundles`
Branch: `codex/backend-preflight-catalog-bundles`
Worktree: `/home/samcantrill/work/loom-worktrees/backend-preflight-catalog-bundles`
PR: https://github.com/samcantrill/loom/pull/163
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase crosses diagnostics and
metadata projections

### Scope

- Goal: expose cheap backend/config/capability diagnostics and preserve
  external/published/location summaries through catalog and bundle metadata.
- Files/modules owned:
  - `src/loom/diagnostics/models.py`
  - `src/loom/diagnostics/preflight.py`
  - run catalog and bundle projection code as needed
  - diagnostics/catalog/bundle tests
- Behavior implemented:
  - Stable Stage 15 check IDs for backend registry availability,
    configured backend handler presence, URI/config validation, capability
    admission, and selected write fail-closed behavior.
  - Default checks avoid network, credentials, checksum probes, payload reads,
    and optional SDK imports.
  - Stage 14 `plugins.metadata` and `plugins.load` results do not satisfy
    Stage 15 backend availability or run-readiness checks.
  - Catalog/bundle metadata preserves external/published/location summaries
    with redacted display fields and unsupported-materialization diagnostics.
- Decisions applied: DAQ-2, DAQ-3, DAQ-4, DAQ-6, DAQ-7, DAQ-9, DAQ-10.
- Examples or docs covered: missing backend handler, invalid URI/config,
  unsupported write, redacted external summary in catalog/bundle output.
- Out of scope:
  - Stage 12 portable-run exchange schema rework beyond preservation hooks.
  - Stage 16 materialization.
  - Authority mutation.
  - Network/credential probes by default.

### Tasks

- Add preflight request/config surface for artifact backend checks only where
  a configured backend declaration exists.
- Add stable check IDs and result details that distinguish plugin metadata
  status from backend readiness.
- Add no-network/no-plugin-import default assertions.
- Add catalog/bundle summary projection helpers.
- Add tests proving secret-bearing values are redacted in diagnostics and
  metadata summaries.
- Add docs for cheap default checks and opt-in expensive probes.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/diagnostics tests/unit/loom/runs tests/contracts` | Target backend preflight, catalog summaries, bundle metadata preservation, and no-network defaults | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: selected write capability failure is a preflight failure;
  metadata-only catalog/bundle preservation still succeeds.
- Design-decision evidence: plugin metadata/import success never marks backend
  availability checks as passed.
- Future-roadmap compatibility evidence: unsupported materialization records
  are visible for Stage 16 without moving payloads.
- Interface, adapter, or protocol reuse evidence: diagnostics consume public
  registry/handler/capability APIs only.
- Documentation evidence: check IDs and default/opt-in behavior are documented.
- Domain-neutrality evidence: diagnostics use fake handlers only.

### Design Impact

This phase makes Stage 15 visible to users. The phase plan must lock check ID
names and failure semantics before implementation.

### Future Compatibility

Stage 16 can add opt-in payload/materialization probes under separate check
IDs or policy flags without changing cheap defaults.

### Alternatives Rejected

- Reusing `plugins.load` as backend availability.
- Always probing credentials or existence.
- Making catalog/bundle preservation fail when payloads are unavailable.

### Debt Introduced

Opt-in expensive checks may need named profiles later. Revisit when Stage 16
or deployments need policy profiles.

### Reviewability

Keep Stage 12 schema changes out of this phase unless they are necessary for
metadata projection tests; Phase 5 owns exchange rework.

### Merge Metadata

- Merged: 2026-05-15 via squash merge to `develop`
- Merge commit: `90e4c1808513d58ddbd83c63136193c7e7074d1b`
- PR: https://github.com/samcantrill/loom/pull/163
- Implementation summary: added explicit artifact-backend preflight targets,
  stable backend registry/handler/capability checks, no-discovery default
  behavior, redacted store summaries, and Stage 15 run metadata projection
  helpers; catalog extraction now thaws artifact metadata so external,
  published, location, and unsupported-materialization summaries remain
  plain-data serializable.
- Checks:
  - Focused Phase 4 pytest paths passed: 26 passed.
  - Broad Phase 4 pytest target passed outside the sandbox: 330 passed / 2
    skipped.
  - `make validate-pr` passed outside the sandbox: Ruff passed, Pyright passed
    with 0 errors, default harness passed with 1649 passed / 26 skipped / 18
    deselected, config-extra passed with 440 passed / 1686 deselected, and
    build passed.
  - `make test-summary` passed: overall 2117 passed / 18 skipped / 1702
    deselected.
  - GitHub CI `checks` job passed on the final PR head in 2m53s.
- Automated review: managing agent local review approved with no blocking or
  non-blocking findings; final pre-merge verification confirmed PR base
  `develop`, head `codex/backend-preflight-catalog-bundles`, successful CI,
  and Phase 4-scoped diff.
- Follow-up notes: branch/worktree cleanup is safe because no successor branch
  depends on Phase 4.

## Phase 5: Stage 12 Exchange Metadata Rework

Status: merged
Slug: `stage-12-exchange-rework`
Branch: `codex/stage-12-exchange-rework`
Worktree: `/home/samcantrill/work/loom-worktrees/stage-12-exchange-rework`
PR: https://github.com/samcantrill/loom/pull/164
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase modifies persisted
run-exchange and bundle metadata behavior

### Scope

- Goal: update Stage 12 portable-run exchange, local bundle export/inspect,
  import result metadata, and related contract tests to consume Stage 15
  external/published/location summaries.
- Files/modules owned:
  - `src/loom/runs/models.py`
  - `src/loom/runs/bundles.py`
  - `src/loom/runs/imports.py`
  - `src/loom/runs/transfer.py` if unsupported-materialization evidence needs
    alignment
  - run exchange, bundle export/import, CLI, and contract tests
- Behavior implemented:
  - Current opaque external-ref extension fields map to Stage 15 summaries or
    a narrow explicit schema field if required.
  - Export/inspect/import preserve summaries as metadata-only records.
  - Unsupported remote materialization/import payload diagnostics are
    structured and do not trigger downloads.
  - Imported runs remain historical/non-resumable unless future stages prove
    equivalent live migration semantics.
  - Authority mutation boundaries from Stage 12 stay unchanged.
- Decisions applied: DAQ-1, DAQ-2, DAQ-7, DAQ-9, DAQ-10.
- Examples or docs covered: metadata-only external ref export, inspect without
  extraction, import preserving external summaries, unsupported
  materialization diagnostic.
- Out of scope:
  - Remote payload materialization.
  - Credential checks.
  - Provider-specific permanent schemas.
  - Authority continuation, merge, overwrite, or live resume policy changes.

### Tasks

- Recheck current `src/loom/runs` source and tests before editing.
- Choose extension-field mapping or a narrow schema revision and record the
  reason in the phase execution plan.
- Add helpers to serialize/deserialize Stage 15 summaries in run exchange.
- Update local bundle export/inspect/import to preserve summaries without
  extraction.
- Add import/readiness diagnostics for unsupported materialization or missing
  backend availability.
- Update CLI/contract tests where user-visible bundle inspect/import summaries
  change.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/runs tests/unit/loom/cli tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_cli_runs_contract.py` | Target run exchange, bundle export/import, inspect output, and CLI contract behavior | yes |
| `make validate-pr` | Full PR gate for phase | yes |

### Acceptance Evidence

- Behavior evidence: external/published/location summaries round trip through
  export/inspect/import without payload reads.
- Design-decision evidence: any schema revision is narrow and justified, or
  extension-field mapping is documented and tested.
- Future-roadmap compatibility evidence: Stage 16 can materialize later using
  preserved summaries.
- Interface, adapter, or protocol reuse evidence: run exchange consumes public
  artifact summaries without importing store internals.
- Documentation evidence: run-catalog/bundle docs distinguish metadata
  preservation from payload transfer.
- Domain-neutrality evidence: tests use fake external summaries only.

### Design Impact

This phase changes durable exchange artifacts. The phase plan must record
schema compatibility, unknown-field behavior, and how old bundles remain
inspectable.

### Future Compatibility

Stage 16 can add explicit materialization/import behavior using the preserved
summaries. Stage 12 historical import safety remains intact.

### Alternatives Rejected

- Keeping external refs permanently opaque.
- Adding remote downloads to bundle import/export.
- Making local bundle archive format the general remote provider protocol.

### Debt Introduced

If extension fields remain the chosen shape, future docs must keep their
meaning stable enough for adapter authors. Revisit if consumers need a
dedicated schema field.

### Reviewability

Keep this phase confined to run-exchange metadata semantics. Do not modify
backend registry or preflight behavior here except through public summaries.

### Merge Metadata

- Merged: 2026-05-15 via squash merge to `develop`
- Merge commit: `4424c0f4bb534ddb154bd05967b28cce11c5bfb7`
- PR: https://github.com/samcantrill/loom/pull/164
- Implementation summary: added the versioned
  `stage_15_artifact_summaries` run-exchange extension and public projection
  helper; local bundle export, inspect, import-record construction, and import
  provenance now preserve Stage 15 summaries without changing the Stage 12
  manifest schema; metadata-only import preserves external artifact metadata in
  historical local artifact indexes; unsupported remote materialization is a
  warning diagnostic rather than an implicit payload operation.
- Checks:
  - Focused Phase 5 pytest paths passed: 26 passed.
  - Broad Phase 5 pytest target passed outside the sandbox: 172 passed / 4
    skipped.
  - `make validate-pr` passed outside the sandbox: Ruff passed, Pyright passed
    with 0 errors, default harness passed with 1653 passed / 26 skipped / 18
    deselected, config-extra passed with 440 passed / 1690 deselected, and
    build passed.
  - `make test-summary` passed: package 90 passed / 1 skipped, unit 1165
    passed / 7 skipped / 1 deselected, contract 227 passed / 2 skipped,
    integration 156 passed / 8 skipped / 13 deselected, e2e 43 passed / 2
    deselected, and config-extra 440 passed / 1690 deselected.
  - GitHub CI `checks` job passed on the final rebased PR head in 4m24s.
- Automated review: managing agent local review approved with no blocking or
  non-blocking findings; final pre-merge verification confirmed PR base
  `develop`, head `codex/stage-12-exchange-rework`, successful CI, and Phase
  5-scoped diff.
- Follow-up notes: branch/worktree cleanup is safe because no successor branch
  depends on Phase 5.

## Phase 6: Examples, Docs, And Validation Hardening

Status: pending
Slug: `external-artifact-docs-validation`
Branch: TBD
Worktree: TBD
PR: TBD
Base branch: TBD
Target branch: TBD
Workflow path: expanded path because this phase validates cross-cutting public
contracts before Stage 16 builds on them

### Scope

- Goal: complete documentation, fake examples, validation matrix, import
  boundary checks, and cross-phase hardening for Stage 15.
- Files/modules owned:
  - feature docs under `docs/features`
  - roadmap implementation-plan completion metadata
  - example fixtures or tests under existing test packages
  - import-boundary and package tests
- Behavior implemented:
  - MLflow-like fake adapter fixture maps tracking URI, artifact URI, run
    identity, redaction, capabilities, lookup, and unsupported operations to
    generic records.
  - Object-store-style fake adapter fixture maps object URI, namespace/prefix,
    consistency hints, checksum support, listing/delete support, and manifest
    policy to the same generic records.
  - Docs clearly label examples as design/contract fixtures, not real
    first-party adapters.
  - Import-boundary tests prove no plugin discovery, backend SDK import, or
    network path runs on package import, CLI help, default preflight, catalog
    listing, or bundle inspect.
  - Validation matrix documents phase-level suite obligations and final test
    evidence.
- Decisions applied: all DAQ decisions.
- Examples or docs covered: MLflow-like and object-store-style fixtures,
  adapter author guidance, remote-stores/artifacts/plugins/preflight/run-catalog
  docs.
- Out of scope:
  - Real adapters.
  - Optional integration suites requiring services.
  - Stage 16 payload operations.

### Tasks

- Update `docs/features/artifacts.md`, `remote-stores.md`, `plugins.md`,
  `preflight.md`, and `run-catalog.md` with final Stage 15 contracts.
- Add or update examples/fixtures for MLflow-like and object-store-style
  mappings.
- Add package/import-boundary tests across artifacts, stores, plugins,
  diagnostics, and runs.
- Add docs/tests proving no optional dependencies are imported by default.
- Run final full validation and record suite-level evidence.
- Update this implementation plan with phase completion metadata when the phase
  PR is prepared or merged.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package tests/contracts tests/unit/loom` | Target package exports, contract fixtures, import boundaries, and unit behavior | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level evidence for final PR body | yes |

### Acceptance Evidence

- Behavior evidence: fake examples use the same generic records and do not
  require optional dependencies.
- Design-decision evidence: docs preserve no-real-backend and no-payload
  boundaries.
- Future-roadmap compatibility evidence: Stage 16 handoff is explicit.
- Interface, adapter, or protocol reuse evidence: adapter author docs describe
  descriptor/factory/registry shape without universal plugin protocol.
- Documentation evidence: feature docs and examples are updated.
- Domain-neutrality evidence: no domain-specific schemas or service clients in
  core.

### Design Impact

This phase validates that the implemented public surface is coherent enough for
later materialization work and optional adapters.

### Future Compatibility

Docs should name Stage 16 as the payload materialization consumer and keep
cleanup/retry/deletion in later roadmap stages.

### Alternatives Rejected

- Documenting examples as supported first-party adapters.
- Adding service-backed integration tests by default.
- Leaving adapter author guidance implicit in tests only.

### Debt Introduced

Example fixtures may need update when the first real adapter is selected.
Revisit when a concrete optional backend family enters the roadmap.

### Reviewability

Keep final docs and validation hardening separate from earlier functional
phases so review can focus on cross-cutting consistency and evidence.

## Cross-Phase Validation

- Full relevant test command: `make validate-pr`
- Final suite evidence command: `make test-summary`
- Targeted artifact tests:
  `uv run pytest tests/unit/loom tests/contracts tests/package`
- Targeted store/plugin tests:
  `uv run pytest tests/unit/loom/pipeline/stores tests/unit/loom/plugins tests/contracts`
- Targeted diagnostics/catalog/exchange tests:
  `uv run pytest tests/unit/loom/diagnostics tests/unit/loom/runs tests/unit/loom/cli tests/contracts`
- Domain-neutrality checks: no concrete service integrations, optional SDKs,
  network requirements, credentials, containers, or external services.
- Import-boundary checks: importing `loom`, `loom.artifacts`,
  `loom.pipeline.stores`, `loom.plugins`, CLI help, default preflight, catalog
  listing, and bundle inspect must not load backend plugin targets or optional
  SDKs.
- Example/demo checks: fake MLflow-like and object-store-style descriptors,
  registry registration, capability admission, redaction, lookup, and
  unsupported-operation results.
- Manual review focus: public API names, schema version policy, Stage 14
  plugin boundary, Stage 12 metadata exchange boundary, Stage 16 materialization
  deferral, and no false run-readiness claims.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Stale Stage 14 dependency in planning | concern | Updated planning and this implementation plan to use the completed Stage 14 implementation plan and landed plugin APIs | resolved |
| Artifact-store plugin readiness ambiguity | concern | Recorded that generic plugin diagnostics stay listing-only while any Stage 15 plugin adapter must be explicit and supplied-registry-based | resolved |
| Stage 12 exchange mapping ambiguity | concern | Phase 5 must choose extension-field mapping or a narrow schema revision after rechecking current source | resolved |

Gate result:

- Status: passed on 2026-05-15
- Review evidence: local equivalent review checked planning readiness,
  maintainability, extensibility, future compatibility, conflicting design
  choices, accepted debt, test strategy, and reviewability using
  `.codex/prompts/implementation-plan-review.md`.
- Accepted risks:
  - Generic Stage 14 plugin diagnostics still classify artifact-store backends
    as listing-only.
  - Adjacent records may require two-record coordination with `ArtifactRef`.
  - Stage 12 exchange may need a narrow schema revision if extension fields are
    insufficient.
  - Capability records may overlap authority capability style.
- Revisit triggers:
  - Stage 15 lands a config-aware backend adapter/check path that can safely
    update plugin readiness wording.
  - Phase 1 proves adjacent summaries are insufficient.
  - Phase 5 proves run-exchange extension fields are ambiguous.
  - A real optional backend exposes missing generic fields or overfitted
    example semantics.

## Final Approval

- Approval status: plan-quality gate passed; ready for Phase 1 execution
  planning
- Approved scope: six-phase Stage 15 implementation shape above, preserving
  Stage 14 plugin metadata boundaries, Stage 12 metadata-only exchange rework,
  Stage 16 payload-materialization deferral, and fake-backend-first validation
- Accepted risks: same as the Plan Quality Gate accepted risks above
- Deferred items:
  - All concrete backend/service integrations.
  - Payload materialization, publish/upload/download, and remote import/export.
  - Credential refresh/storage and default network probes.
  - Automatic global cache lookup and partial stage reuse.
  - Cleanup, retention deletion, retry, timeout, and event policies.
