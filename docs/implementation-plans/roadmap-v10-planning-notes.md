# Roadmap v10 Planning Notes: Run Bundles And Exporters

## Metadata

- Roadmap version: v10
- Source roadmap:
  `docs/implementation-plans/implementation-roadmap.md`
- Roadmap reframing note: this draft was originally created for v9 when run
  bundles were the next roadmap item. The persistence and concurrency
  foundation is now v9, so this bundle/exporter work moved to v10.
- Previous version status: complete for planning. `implementation-plan-v8.md`
  records v8 as implemented with all phases merged, providing the public
  `loom.runs.RunCatalog` facade, current local collection listing,
  rebuildable SQLite sidecar catalog, metadata-only comparison, warning result
  models, and `loom runs index/list/diff` CLI commands.
- Planning notes status: draft
- Current discussion stage: Roadmap framing
- Stage gates:
  - Roadmap framing: briefing prepared; clarification window open
  - Intent discovery: not started
  - Feature brainstorming: not started
  - Functionality and behavior confirmation: not started
  - Context compaction/reset checkpoint: not started
  - Design decision review: not started
  - Phase shaping: not started
  - Handoff: not started
- Related implementation plans:
  - `docs/implementation-plans/implementation-plan-v8.md`
  - No adjacent v11 implementation plan exists yet.
- Related feature docs:
  - `docs/features/run-catalog.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/io.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/loom.md`
  - `docs/structure.md`
- Blockers:
  - None known for planning. Implementation planning must verify the exact v8
    `loom.runs`, run-store freshness, artifact-index, local artifact-store,
    and CLI contracts before phase work begins.

## Roadmap Extraction

Baseline roadmap outcome:

- Add a safe archive and transfer path for completed local runs without
  executing project code.
- Define a run bundle manifest model with format version, entry records,
  checksums, and payload selection metadata.
- Define run exporter result models and a minimal `RunExporter` protocol for
  explicit post-run export operations over completed run metadata, bundle
  manifests, and selected payload references.
- Make metadata-only export the default using standard-library archive support.
- Add explicit artifact and log inclusion flags with size and path reporting.
- Guard export and import against path traversal, symlinks, partially written
  runs, and missing payloads.
- Inspect bundles without extraction.
- Import bundles into a local run collection with manifest validation,
  optional checksum verification, safe path handling, and catalog stale marking
  or refresh.
- Add compatibility exporter hooks that later plugin-discovered integrations
  such as MLflow, DVC, W&B, HTML/static reports, or archival manifest writers
  can reuse without making any external system authoritative.
- Expose CLI commands for export, inspect, and import.
- Add tests for manifest creation, metadata-only bundles, exporter result
  serialization, payload selection, unsafe path rejection, inspect without
  extraction, and import into a temporary run collection.

Prerequisites:

- v0 local runtime kernel: durable local run-store layout, stage state,
  artifact refs, fingerprints, logs, config snapshots, provenance records, and
  conservative resume.
- v1 rebuildable config composition: source records, composition manifests,
  redaction, fingerprints, and provenance that can be archived as metadata.
- v2 CLI core: thin argparse command wrappers, output formatting, JSON envelope
  conventions, and exit-code mapping.
- v3 diagnostics and preflight: local status, logs, and artifact inspection
  patterns that v10 should not duplicate.
- v4 runtime options/resources: normalized runtime metadata and resource models
  that exported metadata may need to preserve.
- v5 stage worker/subprocess execution: attempt, log, and failure records that
  bundles should archive without re-executing.
- v6 and v7 SLURM planning/operations: submission artifacts and submitted
  operation records that bundles may preserve as metadata or optional payloads,
  without requiring live scheduler access.
- v8 run catalog and comparison: public `loom.runs` summaries, direct scan,
  current listing, comparison models, warning taxonomy, and catalog rebuild or
  refresh behavior that import/export should reuse.

Primary feature docs:

- `run-catalog.md`
- `run-store.md`
- `artifacts.md`
- `io.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Remote payload download, remote export/import materialization, and backend
  credential handling.
- Signed bundles, bundle encryption, and cryptographic attestation.
- Large payload deduplication, cross-machine catalog synchronization, and
  incremental catalog watchers.
- Service-specific exporter implementations for MLflow, DVC, W&B, reports, or
  archival systems.
- Automatic post-run exporter dispatch.
- Domain-specific metric extraction, artifact interpretation, comparison
  reports, or payload diffing.
- Plugin discovery for exporter implementations, which is v12; v10 should define
  reusable contracts without loading plugins.
- Sweep orchestration or trial semantics, which are v11; v10 should keep bundle
  behavior useful for ordinary runs that future sweeps can compose.

Compatibility obligations:

- Keep the run store authoritative. Bundles may archive run-store metadata and
  selected payloads, but they must not make the catalog sidecar or exporter
  output authoritative.
- Preserve canonical run identity as `run_uri`. Imported bundles need explicit
  collision and local-path policy rather than resurrecting old `run_id`
  semantics.
- Keep `loom` domain-neutral. Exporters operate on persisted metadata,
  artifact refs, bundle manifests, and selected payload references, not on
  project-specific metric meanings or payload schemas.
- Keep default export conservative and metadata-only so large artifacts, logs,
  remote payloads, or generated submission files are not silently captured.
- Use standard-library archive support unless a concrete design reason justifies
  a dependency.
- Do not execute project code during export, inspection, or import.
- Keep CLI commands as wrappers over public Python APIs. CLI modules should not
  duplicate archive traversal, manifest validation, checksum, or run-store
  path-safety logic.
- Preserve source-tree boundaries: `loom.runs` owns run collection and bundle
  facade behavior, run-store modules own local run-state path helpers,
  artifact-store/I/O modules own artifact URI and checksum primitives where
  applicable, and `loom.cli` owns presentation.
- Default tests must be local, deterministic, filesystem-only, and synthetic.

## Version Briefing

What this version is:

- V10 is the portability and compatibility-export layer for completed local Loom
  runs. It takes the local run-state and many-run catalog foundations from v8
  and adds a safe way to export one run into a portable archive, inspect that
  archive without extraction, and import it into another local run collection.
  It also introduces a small exporter contract for explicit post-run projections
  into external systems or artifact formats, while keeping those external
  systems outside core Loom.

Why this version exists:

- Through v8, Loom can execute runs, inspect individual run directories, list
  collections, filter summaries, and compare metadata. That leaves a practical
  gap: users still need to move or archive a run, review exactly what would be
  included, and restore it somewhere else without copying arbitrary directories
  by hand or relying on domain-specific tooling. V10 closes that gap with a
  manifest-first bundle format, conservative payload defaults, and safety
  checks around archive paths, symlinks, partial runs, and missing payloads.

Impacted or linked work:

- Direct predecessor: v8. V10 should reuse `RunCatalog` and catalog summary
  models where useful, and import should leave the derived catalog rebuildable
  or explicitly stale/refreshed. The SQLite sidecar remains derived data and
  should not be stored as bundle truth.
- Direct successor: v11. Sweeps are many ordinary runs. V10 bundles should not
  add sweep semantics, but the archive format and import behavior should not
  make future trial-level bundling difficult.
- Later successor: v12. Plugin discovery will eventually load exporter
  implementations. V10 should define the exporter protocol and result models
  without doing entry point discovery or service-specific integration work.
- Later successors: v13 and v14 remote stores may require metadata-only remote
  references or explicit remote payload staging. V10 should keep local payload
  inclusion policy clear enough that remote payload behavior can be added later
  without changing the manifest vocabulary.
- Later successor: v18 cleanup and retention may use export/import metadata, so
  V10 should make bundle contents, checksums, and payload selection explicit.

Likely public surfaces and durable artifacts:

- Public Python models for bundle manifests, bundle entries, payload selection,
  inspection summaries, import/export results, and exporter results.
- A minimal `RunExporter` protocol for explicit post-run export operations.
- Public API methods or functions for export, inspect, and import. The exact
  home is not confirmed yet; repo evidence points toward extending the
  `loom.runs` namespace while keeping lower-level run-store and artifact-store
  path logic in their owning modules.
- CLI commands for export, inspect, and import. The final CLI grouping is not
  confirmed yet because the feature doc still shows top-level examples while v8
  established the `loom runs ...` command group.
- Durable archive contents including a schema-versioned bundle manifest,
  selected run metadata, provenance and state files, artifact refs, optional
  logs, optional artifact payloads, and per-entry checksums and sizes.
- Import-side run collection updates and catalog stale/rebuild behavior.

Structure rationale:

- The version is structured as one coherent project-plan unit because it has
  one primary user-visible outcome: safe local run portability. It affects one
  main package cluster, centered on run collections, run-store metadata,
  artifact references, I/O checksums, and CLI presentation. It introduces one
  major durable schema family, the bundle manifest. External adapters, remote
  payload operations, signing/encryption, and automatic dispatch are explicitly
  deferred, keeping v10 reviewable without mixing unrelated integration systems.

Visible assumptions, risks, and constraints:

- The default bundle is metadata-only. Payload inclusion should be explicit and
  inspectable, especially for large artifacts and logs.
- Archive inspection should trust the manifest enough to summarize the bundle
  but should still validate archive member safety before any extraction path is
  considered.
- Import needs a clear collision policy for an existing run URI or target run
  directory. The repo evidence favors explicit safe behavior over silent
  overwrite.
- Symlink and path traversal rules need to be strict enough for archive safety
  while still preserving useful metadata about symlinked or external artifacts.
- Compatibility exporters should probably be explicit function/protocol calls in
  v10, not plugin-discovered adapters, because plugin discovery is v12.
- Exporter contracts must not interpret metric schemas, artifact payloads, or
  external tracker semantics. They should receive persisted metadata and
  selected references.
- Standard-library archive support likely means tar/gzip first. Compression
  format and CLI naming still need confirmation.
- Partial, actively changing, or running runs need a conservative policy:
  reject by default or require an explicit unsafe/force mode. The roadmap
  emphasizes partially written run safety checks but does not yet settle whether
  forced export exists.
- The current v8 catalog warnings and freshness tokens give useful safety
  signals, but v10 planning must verify whether bundle export should read
  through `RunCatalog`, direct run-store APIs, or both.

User clarification questions and resolved answers:

- Clarification: What functionality is export/bundle intended to provide?
  Resolved answer: A run bundle is meant to be a portable, manifest-described
  archive of one completed Loom run's persisted metadata, with optional
  explicitly selected payloads such as artifact files and logs. It lets a user
  freeze, share, move, review, and later import a run into a local run
  collection without executing project code, manually copying an arbitrary run
  directory, or relying on a hosted experiment tracker. The bundle manifest
  makes the contents inspectable before extraction or import: format version,
  source run identity, entry paths, entry kinds, checksums, sizes, and payload
  selection policy. Metadata-only export is the conservative default so users
  can archive provenance, state, config snapshots, artifact refs, fingerprints,
  statuses, and summaries without accidentally including large outputs. Explicit
  inclusion flags can add artifact payloads or logs when the user wants a more
  complete transfer. Import validates the manifest, rejects unsafe archive
  paths, verifies checksums when requested, writes the run into a target local
  collection under a safe collision policy, and refreshes or marks derived
  catalog state stale. Compatibility exporters are related but distinct: they
  provide an explicit protocol for projecting completed run metadata and bundle
  references to external formats or tools later, without making those tools the
  source of truth.
- Clarification: Is migration between different stores or environments
  essentially the feature set, including an option to migrate full artifact
  bundles?
  Resolved answer: Yes, with a scoped v10 boundary. V10 should treat run bundles
  as the core migration mechanism for moving completed runs between local run
  collections or separate environments. The minimum migration unit is a
  metadata-only bundle that preserves run identity, status, provenance, config
  snapshots, artifact refs, fingerprints, and catalog-compatible summaries.
  V10 should also provide explicit fuller migration modes that include local
  artifact payloads and logs when requested, with manifest size/path/checksum
  reporting so users can see what is being moved. The boundary is that v10 should
  not perform remote payload downloads or backend-to-backend synchronization by
  default; if an artifact ref points to a non-local or unavailable payload, v10
  should preserve the ref metadata and report the missing or remote payload
  clearly unless a later remote-store version adds explicit materialization.

## User Intent

Target audience:

- TBD

User-visible outcome:

- TBD

Success criteria:

- TBD

Non-goals:

- TBD

Constraints:

- TBD

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Repo-derived v10 scope is safe run export, inspect, import, and explicit exporter contracts over completed persisted metadata. Clarified that bundles enable freezing, sharing, moving, reviewing, and importing completed runs through a manifest-described archive rather than arbitrary directory copying or external tracking services. Clarified that environment/store migration is the core user value, with explicit artifact/log payload inclusion modes for fuller migration. | Metadata-only export by default; no project-code execution; standard-library archive support; external integrations deferred; remote payload materialization deferred. | Further user clarifying questions; user priority for v10 planning; target audience and outcome. | Confirm roadmap framing and move to intent discovery. |
| Intent discovery |  |  |  |  |
| Feature brainstorming |  |  |  |  |
| Functionality and behavior confirmation |  |  |  |  |
| Context compaction/reset checkpoint |  |  |  |  |
| Design decision review |  |  |  |  |
| Phase shaping |  |  |  |  |
| Handoff |  |  |  |  |

## Brainstormed Capabilities

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Metadata-only run bundle export | maybe | Roadmap baseline and likely default behavior. | Awaiting functionality confirmation. |
| Explicit artifact payload inclusion | maybe | Roadmap baseline and needed for full local run migration; needs size/path reporting and safety policy. | Awaiting behavior confirmation. |
| Explicit log inclusion | maybe | Roadmap baseline; log scope and generated submission logs need confirmation. | Awaiting behavior confirmation. |
| Full local run migration bundle | maybe | User clarified migration between environments/stores as the core feature value. | Should include metadata plus explicitly selected local payloads/logs, while preserving refs for unavailable remote payloads. |
| Bundle inspection without extraction | maybe | Roadmap baseline and safety requirement. | Awaiting behavior confirmation. |
| Import into local run collection | maybe | Roadmap baseline; collision and catalog refresh policy need confirmation. | Awaiting behavior confirmation. |
| Minimal compatibility exporter protocol | maybe | Roadmap baseline; plugin discovery and concrete adapters deferred. | Awaiting design review. |

## Confirmed Functionality And Behavior

Included functionality:

- TBD

User-visible behavior:

- TBD

Default behavior:

- TBD

Failure behavior and diagnostics:

- TBD

Explicit deferrals:

- TBD

Out-of-scope behavior:

- TBD

Context compaction/reset checkpoint:

- Checkpoint status: not reached
- Notes path: `docs/implementation-plans/roadmap-v10-planning-notes.md`
- Resume instruction: Reload this planning notes file and
  `.codex/prompts/roadmap-version-planning-notes-facilitate.md`, then continue
  from the current discussion stage.
- Functionality and behavior reopened after checkpoint: not applicable

## Design Decision Review Queue

| Decision | Why it matters | User feedback needed | Status |
| --- | --- | --- | --- |
|  |  |  | draft / reviewing / confirmed / deferred |

## Design Decisions

| Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Debt and revisit trigger |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |

## Practical Design Notes

Public Python API surface:

- TBD

CLI surface:

- TBD

Persisted records and file layout:

- TBD

Import boundaries and dependencies:

- TBD

Failure modes and diagnostics:

- TBD

Extension points and flexibility boundaries:

- TBD

Maintainability assessment:

- TBD

Extensibility assessment:

- TBD

Flexibility and expansion assessment:

- TBD

Scalability and future compatibility:

- TBD

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
|  |  |  |

## Phase Sketch

### Phase <N> - <Title>

Goal:

- TBD

Scope:

- TBD

Out of scope:

- TBD

Acceptance criteria:

- TBD

Test expectations:

- Package:
- Unit:
- Contract:
- Integration:
- E2E:
- Opt-in:

Design impact:

- TBD

Future compatibility:

- TBD

Alternatives rejected:

- TBD

Debt introduced:

- TBD

Reviewability:

- TBD

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Does the user have clarifying questions about the v10 briefing before intent discovery? | Roadmap framing | Answer clarifications before moving forward. | open |
| What should v10 optimize for relative to the roadmap description? | User intent, success criteria, phase shaping | Conservative portability and safety before exporter breadth. | open |
| How complete should the first full-payload migration mode be? | Export behavior, import behavior, phase shaping | Include local artifact payloads and logs explicitly; preserve and report unavailable remote refs rather than materializing them. | open |
| Should partial or actively changing runs be rejected by default with no force mode in v10? | Export behavior and diagnostics | Reject by default; discuss any explicit force mode during behavior confirmation. | open |
| Should CLI commands live under `loom runs` or as top-level `loom export/inspect/import` commands? | CLI surface | Defer to design review after functionality is confirmed. | open |
