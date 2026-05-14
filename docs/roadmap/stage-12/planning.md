# Roadmap v12 Planning Notes: Run Bundles, Transfer, And Exporters

## Metadata

- Roadmap version: v12
- Source roadmap: `docs/roadmap.md`
- Previous version status: `docs/roadmap/stage-11/implementation-plan.md` has passed its plan
  quality gate. V11 Phases 1 through 8 are recorded as merged on `develop`;
  Phase 9, the operational UX, minimal CLI wrapper, docs, and hardening phase,
  remains pending in the local plan at planning startup. V12 planning may
  proceed from the locked v11 queue assumptions, but implementation-plan
  drafting should refresh against the final v11 Phase 9 surfaces before naming
  concrete CLI/preflight integration points.
- Planning notes status: draft
- Current discussion stage: context compaction/reset checkpoint recorded; design
  agreement pending after resume.
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: recorded; reset needed before design
  - Design agreement review: pending
  - Design safety review: pending
  - Examples and validation strategy: pending
  - Phase shaping: pending
  - Implementation readiness: pending
  - Handoff: pending
- Related implementation plans:
  - `docs/roadmap.md`
  - `docs/roadmap/stage-11/implementation-plan.md`
  - `docs/roadmap/stage-10/implementation-plan.md`
  - `docs/roadmap/stage-11/planning.md`
  - `docs/roadmap/stage-10/planning.md`
- Related feature docs:
  - `docs/features/run-catalog.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/io.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/features/remote-stores.md`
  - `docs/features/slurm.md`
  - `docs/features/plugins.md`
- Blockers:
  - None for roadmap-stage planning.
  - Implementation-plan drafting must refresh the current v11 completion state
    and must not claim final queue CLI/preflight integration points until v11
    Phase 9 has either landed or been carried forward explicitly.
  - Import semantics now need explicit planning around how bundles, offline
    evidence, authority import, and local run-collection import share one
    import/export contract without weakening the strict v10 safety policy.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V12 provides safe run export, transfer-interface verification, bundle inspect/import, and compatibility exporter contracts with portable manifests. | roadmap scope | This is the baseline scope for planning. |
| `docs/roadmap.md` | V11 defers full run bundle transport, remote artifact payload movement, and proof of complete remote workspace equivalence to v12. | prerequisite and dependency gap | V12 must close the queue/delegated-launch evidence gap without redesigning queue scheduling. |
| `docs/roadmap/stage-11/implementation-plan.md` | V11 keeps queue policy separate from authority truth, records launch contracts, and leaves delegated SLURM launch on shared/pre-staged workspace assumptions until bundle transport exists. | v12 handoff | V12 should provide reusable verification records that queue adapters can cite rather than making the queue parse bundle internals. |
| `src/loom/queue/models.py` | `LaunchContract` already has `snapshot`, `drift_inputs`, and `delegated_verification` mappings. | current code seam | Transfer evidence can connect to this existing enqueue-time contract shape. |
| `src/loom/queue/slurm.py` and `tests/contracts/test_queue_delegated_slurm_contract.py` | Delegated SLURM produces verification evidence listing proven and unproven checks, with `shared_workspace` currently unproven in the sample contract. | current queue evidence behavior | V12 can turn bundle/transfer checks into concrete proven/unproven evidence without overstating remote equivalence. |
| `docs/features/run-catalog.md` | The catalog owns export/import/inspect at the feature-doc level, but v8 implemented only catalog index/list/diff. The doc describes manifests, metadata-only default, safety checks, inspect without extraction, and import into local run collections. | feature ownership and behavior | V12 should extend `loom.runs` rather than creating an unrelated product surface. |
| `src/loom/runs/catalog.py`, `src/loom/runs/models.py`, and `tests/contracts/test_run_catalog_contract.py` | Current public catalog APIs support rebuild, scan, list, and compare over `RunSummary`/`RunComparison`; no export/import public APIs exist yet. | current code boundary | V12 can add bundle APIs beside the catalog facade while preserving current list/diff behavior. |
| `docs/features/run-store.md` | Run store and authority-backed stores are truth for run/stage lifecycle, attempts, artifact records, provenance, and materialized projections; local files remain payload/projection surfaces after v9/v10. | authority boundary | Bundle export should read authority-backed metadata where available and treat local materialization as payload/projection, not lifecycle truth. |
| `src/loom/pipeline/stores/materialization_read_models.py` | `read_completed_run_bundle_metadata(...)` returns payload-free completed-run metadata, artifact facts, cleanup candidates, materialized refs, and warnings. | likely metadata source | This is the strongest existing v12 input seam and should be preserved or extended rather than bypassed. |
| `docs/features/artifacts.md` | `ArtifactRef` is generic metadata; project code owns domain artifact meaning. Artifact stores save/register/load/verify payloads and local stores own safe local path resolution. | artifact boundary | Bundle selection can include payload bytes, but exporter contracts must not interpret domain semantics. |
| `docs/features/io.md` | I/O owns URI parsing, local sources, codecs, and optional future source backends; remote write backends and heavyweight clients are deferred. | dependency and transfer boundary | V12 should use standard-library local archive/URI behavior and avoid remote-store dependencies. |
| `docs/features/cli.md` | CLI is a thin outer layer over Python APIs; bundle commands are deferred command families and should not reimplement store/export logic. | CLI surface | V12 CLI should call bundle/export/import APIs and format results. |
| `docs/features/testing.md` | Default tests should use local temporary directories, synthetic pipelines, fake adapters, and no real clusters, network, or heavyweight services. | validation strategy | Bundle tests should be deterministic and local by default. |
| `docs/structure.md` | Target source tree places run catalog under `src/loom/runs`, stores under `src/loom/pipeline/stores`, I/O under `src/loom/io`, and CLI as the outermost layer. | module ownership | V12 should respect these boundaries. |
| `src/loom/authority/offline_import.py`, `src/loom/pipeline/offline_evidence.py`, and `tests/integration/authority/test_offline_import_api.py` | V10 offline import validates complete terminal non-authoritative evidence, rejects collisions, imports into authority, records replay events, and marks import provenance as `historical_only: true`, `resumable_live: false`, and `strict_reject_collisions`. | offline import alignment | V12 should align bundles/importers with this safety contract rather than creating a second incompatible import path. |

## Exploration Coverage

| Area | Files or patterns checked | Findings | Gaps |
| --- | --- | --- | --- |
| Roadmap and workflow docs | `.codex/workflows/roadmap-stage-planning.md`, `docs/roadmap.md`, v12/v11/v13 sections | V12 is a bounded post-queue bundle/exporter step, before sweeps and plugin discovery. | None for startup framing. |
| Prior and adjacent plans | `docs/roadmap/stage-11/implementation-plan.md`, `docs/roadmap/stage-11/planning.md`, `docs/roadmap/stage-10/planning.md` | V11 leaves bundle-backed remote equivalence for v12; v10/v11 authority surfaces require strict source-of-truth separation. | Refresh v11 Phase 9 status before implementation-plan drafting. |
| Feature docs | `run-catalog.md`, `run-store.md`, `artifacts.md`, `io.md`, `cli.md`, `testing.md` | Feature docs already place export/import under run catalog, payload refs under artifacts/stores, URI/archive behavior under I/O, and command presentation under CLI. | `remote-stores.md` and `plugins.md` may need a targeted read before design agreement. |
| Source and tests | `src/loom/runs/*`, `src/loom/pipeline/stores/materialization_read_models.py`, `src/loom/queue/*`, `src/loom/authority/offline_import.py`, `src/loom/pipeline/offline_evidence.py`, run-catalog, queue, and offline-import contract/integration tests | Catalog list/diff, completed-run bundle metadata, queue launch verification, and strict offline-evidence import seams exist; bundle/export/import and generic importer/exporter modules do not. | Detailed source design should inspect local store path helpers, CLI command registration, archive safety helpers, and authority import adapter boundaries before implementation-plan drafting. |

## Roadmap Extraction

Baseline roadmap outcome:

- Add safe, portable run bundles for completed run metadata and selected
  materialized payloads.
- Add transfer-interface verification evidence that v11 remote/pre-staged
  launchers can reference before claiming workspace equivalence.
- Add explicit compatibility-export contracts for projecting completed Loom run
  facts into later external tools without making those tools authoritative.
- Add CLI commands for export, inspect, and import.

Prerequisites:

- V8 run catalog list/diff surface and rebuildable local catalog model.
- V9/v9-post/v10 authority-backed run lifecycle and materialization read models.
- V11 queue launch contracts and delegated-verification reporting.
- Existing local run artifact/materialization helpers, artifact refs, file URI
  helpers, and standard-library serialization/archive behavior.
- V10 offline evidence and offline import semantics, especially terminal-only
  import, conflict rejection, authority mutation through the authority service,
  and historical/non-resumable provenance.

Primary feature docs:

- `run-catalog.md`
- `run-store.md`
- `artifacts.md`
- `io.md`
- `cli.md`
- `testing.md`

Deferred or out-of-scope roadmap work:

- Signed bundles.
- Large payload deduplication.
- Cross-machine catalog synchronization.
- Bundle encryption.
- Service-specific exporter implementations.
- Automatic post-run exporter dispatch.
- Domain-specific comparison reports.
- Remote artifact payload movement beyond local bundle/transfer evidence.
- Plugin discovery for third-party run exporters; v14 owns entry point loading
  after the v12 protocol exists.

Compatibility obligations:

- Exporter contracts must operate on persisted Loom run metadata, artifact
  refs, bundle manifests, and selected payload references, not domain metric
  semantics.
- Bundle export must not execute project code.
- Bundle inspect must not extract files to the current directory.
- Bundle import must validate manifests, reject unsafe paths, verify checksums
  when requested, and mark or refresh catalog state explicitly.
- Bundle/importer semantics must align with v10 offline import so Loom does not
  grow two incompatible ways to migrate completed runs between workspaces or
  stores.
- Default export must be metadata-only and conservative about large payloads.
- Queue/delegated-launch transfer evidence must be concrete and machine-readable
  without turning the queue into bundle-format owner.
- V12 must keep optional external tools such as MLflow, DVC, W&B, or static
  report writers as future compatibility consumers, not required dependencies.
- Unsupported transfer operations should fail explicitly. Python transfer
  handler calls may raise `NotImplementedError`; CLI or structured APIs should
  return a machine-readable unsupported-transfer diagnostic instead of silently
  falling back.

## Version Briefing

What this version is:

- V12 is Loom's first run-bundle and compatibility-export version. It creates a
  portable archive/manifest format for completed runs, lets users inspect and
  import those bundles safely, records transfer-interface evidence for queued or
  delegated launches, and defines a small exporter protocol that later plugins
  can implement.

Why this version exists:

- V8 gave Loom a local run catalog for finding and comparing runs, but not a way
  to safely move or archive run records.
- V10 made authority-backed lifecycle state the runtime truth, which means
  export/import must distinguish authoritative metadata from local materialized
  payloads and projections.
- V11 queue/delegated dispatch intentionally stops short of proving full remote
  workspace equivalence. V12 supplies the evidence model and bundle/transfer
  artifacts that can close that gap without forcing Kubernetes, cloud storage,
  SSH transport, or a remote artifact backend into core.
- V10 already has strict offline evidence import into authority. V12 should
  treat that as an existing import safety contract to align with, not as a
  parallel feature to ignore.
- Later sweeps, plugins, remote stores, cleanup, and external tool adapters all
  benefit from a stable run-export contract.

Impacted or linked work:

- `loom.runs` likely owns public bundle APIs because run-catalog feature docs
  already include export, inspect, and import.
- `loom.pipeline.stores` remains the source for authoritative completed-run
  metadata and materialized-ref classification.
- `loom.artifacts` and artifact stores supply payload refs and checksum facts
  without interpreting payload meaning.
- `loom.io` supplies URI/path/archive-adjacent helpers and keeps remote clients
  out of default dependencies.
- `loom.queue` should consume transfer evidence through existing launch-contract
  and delegated-verification fields rather than owning bundle internals.
- `loom.authority` offline import should either use the shared importer core or
  become a compatibility adapter over it, while preserving the existing strict
  validation, collision rejection, replay evidence, and historical-import
  provenance.
- `loom.cli` should expose thin `export`, `inspect`, and `import` wrappers over
  Python APIs.
- V13 sweeps should remain ordinary runs that v12 bundle tools can inspect.
- V14 plugin discovery can later load exporter plugins after the v12 protocol
  exists.

Likely public surfaces and durable artifacts:

- Public Python value models for bundle manifests, manifest entries, payload
  selection policy, bundle inspection results, import results, transfer
  verification records, exporter/importer results, and minimal `RunExporter`
  and `RunImporter` protocols.
- Public bundle operations for exporting a completed run, inspecting a bundle
  without extraction, importing into a local run collection, and importing
  accepted run evidence into authority through a shared importer contract.
- A versioned manifest document inside every bundle with format version, source
  run identity, authority schema facts, entry records, checksums, payload
  selection metadata, materialization warnings, and compatibility metadata.
- CLI commands for export, inspect, and import with text and JSON output.
- Catalog stale marking or refresh behavior after import.

Structure rationale:

- The roadmap places v12 after queue dispatch because queue adapters can record
  only partial shared/pre-staged workspace assumptions until bundle/transfer
  evidence exists.
- It places v12 before sweeps because sweeps should create ordinary runs that
  the bundle tools can archive and inspect, not a parallel sweep-specific export
  format.
- It places v12 before plugin discovery because core must define the exporter
  protocol before external packages can register exporter implementations.
- The default should use standard-library archive support to keep the runtime
  dependency-light and local-testable.

Visible assumptions, risks, and constraints:

- Planning assumes v12 should begin with local filesystem bundles and local run
  collections, not remote object stores or cross-machine catalog sync.
- Planning assumes bundle export is for terminal/completed runs by default. The
  existing `read_completed_run_bundle_metadata(...)` helper warns on
  non-terminal runs and is a natural seam to preserve.
- Planning now assumes bundles and offline import should be aligned so they can
  support migration of completed runs between workspaces or stores. The
  unresolved part is whether v12 should only refactor/adapterize the existing
  historical import path or also introduce a new user-visible bundle-to-authority
  import command.
- The biggest design risk is mixing authority truth, local materialized payloads,
  and imported projections into one ambiguous "run copy" concept.
- The second major risk is over-promising exporter extensibility before plugin
  discovery and external tool adapters exist.
- The main safety risks are path traversal, symlinks, partially written runs,
  missing payloads, checksum mismatch, unexpected large payloads, and import
  collisions.
- The main scope risk is accidentally taking on transport implementation,
  encryption/signing, deduplication, automatic exporter dispatch, or
  domain-specific report semantics too early.

User clarification questions and resolved answers:

- User said "Proceed" after the startup briefing. Treat this as no clarifying
  questions, confirmation of the recommended planning priority, and permission
  to move into intent discovery.

## User Intent

Target audience:

- Researchers and operators who need safe local archive, transfer, review, and
  restore workflows for completed Loom runs, plus maintainers of future
  exporter/plugin adapters.

User-visible outcome:

- A user can export a completed run conservatively, inspect the bundle without
  extraction, import it into a local run collection or authority-backed target
  using the same importer contract as offline evidence, and see transfer
  evidence that queue/delegated launchers can cite.

Success criteria:

- Bundle import/export and offline import converge on shared importer/exporter
  abstractions rather than remaining parallel paths.
- Unsupported transfer kinds fail explicitly with `NotImplementedError` in
  Python handler paths or structured unsupported-transfer diagnostics at the CLI
  boundary.
- No external exporter/importer implementations ship in v12.
- V12 records resume-readiness metadata and hook points for migrated runs, while
  runner/planner live resume from migrated imports remains disabled with a
  structured diagnostic.

Non-goals:

- Roadmap defaults already defer signed/encrypted/deduplicated bundles,
  external service exporters, automatic exporter dispatch, and domain-specific
  reports.
- Actual migrated live resume is deferred until a later roadmap defines
  target-authority/store equivalence, artifact rebasing, and planner reuse
  policy.

Constraints:

- Keep Loom domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Avoid heavyweight runtime dependencies.
- Keep default validation local and deterministic.
- Preserve strict v10 offline import safety semantics unless a later confirmed
  decision explicitly changes them.

## Workflow Stage Readback

Record an explicit narrative readback before or after any context checkpoint so
later passes can resume without rediscovering what was already confirmed.

Roadmap framing locked decisions:

- V12 planning starts from the roadmap scope: run bundles, transfer-interface
  evidence, safe inspect/import, and minimal exporter contracts.
- Planning priority is safe conservative archive/import first, concrete v11
  transfer evidence second, and minimal exporter hooks third.
- No clarification questions were raised before moving into intent discovery.

Intent discovery locked decisions:

- Bundles should align with offline import instead of becoming a separate import
  universe.
  - V12 should consider refactoring offline import to use shared bundle/importer
    contracts or wrapping offline evidence as a compatibility importer source.
  - V12 should consider the interface and durable metadata required for
    resumable migrated runs, but implementation should likely be deferred until
    Loom has a designed target-authority/store equivalence and artifact-ref
    rebasing policy.
  - Transfer handler scope remains intentionally narrow; unsupported transfer
    kinds should fail explicitly until concrete handlers are added in later
    roadmap work.
- V12 should introduce both `RunExporter` and `RunImporter` as core protocols,
  with no external implementations for now.
- V12 should provide resume-readiness metadata and hooks, but actual migrated
  live resume remains unsupported/deferred.

Capability triage and candidate-functional-requirement readback:

- Confirmed. The included capability set covers bundle manifests,
  metadata-only export, explicit payload/log inclusion flags, transfer evidence,
  inspect without extraction, safe import with target-local identity, minimal
  `RunExporter`/`RunImporter`, offline-import alignment, resumable-migration
  readiness hooks, and explicit unsupported-transfer behavior. Deferred
  capabilities include concrete transfer handlers, external implementations,
  automatic dispatch, signing, encryption, deduplication, cross-machine
  synchronization, and live migrated resume.

Functionality-agreement readback:

- Confirmed. Bundle/offline import/export should share core importer/exporter
  contracts while preserving v10 strict import safety. Imported copies use a
  target-local identity, reject target collisions, and preserve the source
  `run_uri` and bundle/evidence identity as provenance. Imports remain
  terminal, historical, and non-resumable in v12, with resume-readiness metadata
  and explicit blockers reserved for future live migration work.

Functionality and behavior confirmation readback:

- Confirmed. V12 will export terminal completed-run metadata and selected
  payload/log entries into local versioned bundles, inspect bundles without
  extraction, import bundles or offline evidence through a shared importer
  contract, record target-local import identity plus source provenance, publish
  queue-consumable transfer evidence, define minimal importer/exporter
  protocols, and report resumable-migration readiness blockers without enabling
  migrated live resume.
- Default behavior is metadata-only export, standard-library local archives, no
  project code execution during export/inspect/import, no extraction during
  inspect, target-local import identity with collision rejection, explicit
  unsupported-transfer diagnostics, and fail-closed migrated-live-resume
  behavior.
- Failure behavior covers non-terminal run, unsupported schema, active run
  changed during read, unsafe path, symlink surprise, missing payload, checksum
  mismatch, unexpected large payload, import collision, unsupported archive
  format, stale catalog state, unsupported transfer kind, invalid or incomplete
  offline evidence, and resume blocked for migrated imports.

Design-agreement follow-up:

- Resume from this checkpoint, reload the moved planning artifact at
  `docs/roadmap/stage-12/planning.md`, and treat the confirmed functionality
  and behavior baseline as binding unless the user explicitly reopens it.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Startup briefing confirmed from roadmap, feature docs, v11 handoff, and current source seams. Planning priority is safe conservative archive/import first, concrete v11 transfer evidence second, and minimal exporter hooks third. | Metadata-only local export by default; no project code execution; inspect without extraction; exporter hooks stay minimal. | None for framing. | Intent discovery. |
| Intent discovery | Bundles should align with offline import; unsupported transfer kinds fail explicitly; v12 should introduce both `RunExporter` and `RunImporter`; no external implementations ship now; v12 adds resume-readiness hooks but not migrated live resume. | Preserve v10 strict import safety and historical/non-resumable provenance for executable behavior; add resume-readiness metadata/hooks without enabling live continuation. | None for intent discovery. | Capability triage. |
| Capability triage and candidate functional requirements | Include bundle manifests, metadata-only export, explicit payload/log flags, transfer evidence, inspect without extraction, safe import, minimal exporter/importer protocols, offline-import alignment, resumable-readiness hooks, and unsupported-transfer diagnostics. Defer concrete transfer handlers, external implementations, automatic dispatch, signing/encryption/dedupe/sync, and live migrated resume. | Conservative local archive/import first; queue transfer evidence second; minimal exporter/importer hooks third. | None. | Confirm behavior baseline. |
| Functionality agreement review | Shared importer/exporter contract is accepted; v10 strict import safety is preserved; imported runs use target-local identity with source identity in provenance; imported runs remain terminal historical/non-resumable in v12. | Reject collisions by default; do not execute project code; record resume-readiness blockers instead of enabling live migrated resume. | None. | Lock behavior baseline. |
| Functionality and behavior confirmation | Confirmed export, inspect, import, transfer evidence, importer/exporter protocols, readiness metadata, explicit unsupported-transfer behavior, and deferrals. | Metadata-only local archive by default; no project code execution; no inspect extraction; target-local import identity with source provenance; collision rejection; migrated live resume disabled. | None. | Proceed to design agreement after context reset/resume. |
| Context compaction/reset checkpoint | This planning artifact has moved to `docs/roadmap/stage-12/planning.md`; confirmed functionality and behavior are now the source of truth. | Resume design agreement from the moved artifact and do not reopen requirements unless explicitly requested. | None. | Reload context and draft implementation shape plus design queue. |
| Design agreement review | Pending | Pending | Pending | Draft implementation shape and design queue after context reset/resume. |
| Design safety review | Pending | Pending | Pending | Run bounded design-safety review. |
| Examples and validation strategy | Pending | Pending | Pending | Map examples to tests and checks. |
| Phase shaping | Pending | Pending | Pending | Shape implementation phases. |
| Implementation readiness | Pending | Pending | Pending | Resolve blockers before implementation-plan drafting. |
| Handoff | Pending | Pending | Pending | Prepare confirmed notes for implementation-plan draft. |

## Capability Triage

Confirmed capability list from roadmap evidence, repo seams, and user intent.

| Capability | Decision | Rationale | Notes |
| --- | --- | --- | --- |
| Versioned run bundle manifest | include | Roadmap names manifest model with format version, entries, checksums, and payload selection metadata. | Must distinguish authority metadata from payload/materialization refs. |
| Metadata-only export by default | include | Roadmap exit criteria require conservative default export that avoids large unexpected payloads. | Payload flags can broaden selection explicitly. |
| Explicit artifact/log inclusion flags | include | Roadmap names artifact/log inclusion and size/path reporting. | Need safe size/path summaries before archive write. |
| Transfer-interface verification records | include | V11 leaves remote/pre-staged equivalence unproven without v12 evidence. | Should be consumable by queue launch contracts without queue owning bundle format. |
| Bundle inspect without extraction | include | Roadmap and feature doc both require inspection without extraction. | Should support checksum verification on request if feasible. |
| Safe import into local run collection | include | Roadmap requires manifest validation, safe paths, checksums, and catalog stale marking. | Imported copies use target-local identity and source provenance. |
| Minimal compatibility exporter protocol | include | Roadmap names `RunExporter` and future MLflow/DVC/W&B/static report hooks. | Keep protocol small until v14 plugin discovery and concrete adapters exist. |
| Minimal compatibility importer protocol | include | User direction asks for `RunImporter` aligned with offline import and bundle import. | Should cover bundle import and offline evidence import without external implementations. |
| Offline import alignment/refactor | include | User direction says bundles and offline import should do the same kind of migration work. | Preserve existing v10 strict evidence validation and authority mutation semantics while removing duplicate import concepts. |
| Resumable migration interface hooks | include | User confirmed v12 should provide readiness metadata and hooks while actual migrated live resume remains deferred. | Include durable resume-eligibility/readiness records and extension hooks; do not make imported runs live-resumable in v12 by default. |
| Transfer handler unsupported behavior | include | User direction says leave concrete transfer handler scope for now and fail explicitly. | Python can use `NotImplementedError`; CLI/structured APIs should return unsupported diagnostics. |
| Automatic exporter dispatch | defer | Roadmap explicitly defers automatic post-run exporter dispatch. | Future reliability/event-sink work may revisit. |
| External service-specific exporters | defer | Roadmap explicitly defers service-specific implementations. | Protocol only in v12. |
| Signed, encrypted, deduplicated, cross-machine synchronized bundles | defer | Roadmap explicitly defers these. | Keep default local and dependency-light. |
| Domain-specific reports/comparison | out of scope | Loom must remain domain-neutral and exporter contracts must not interpret metric semantics. | Future plugins may project generic records. |

## Functionality Agreement Queue

| ID | Requirement or decision | Depends on | Resolution order | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| FRQ-1 | Shared import/export contract across bundles and offline evidence | Roadmap framing, intent discovery | 1 | Introduce `RunExporter` and `RunImporter` protocols and make bundle import/export plus v10 offline import align around them. Do not delete the v10 import safety semantics; refactor or adapterize them behind the shared importer. Imported runs stay historical/non-resumable in v12, with resume-readiness metadata and blockers recorded for later work. | Prevents two competing migration/import concepts before remote stores and cross-workspace workflows arrive while preserving the strict v10 safety policy. | Prior intent discovery resolved the live-resume branch: v12 should add readiness hooks but not implement migrated live continuation. | confirmed |
| FRQ-2 | Bundle/import collision and identity policy | FRQ-1 | 2 | Allocate or use a target-local run identity for the imported copy; preserve source run metadata, source `run_uri`, and bundle/evidence identity in import provenance; reject target collisions by default; do not silently overwrite or execute project code. | Import identity affects catalog behavior, authority mutation, and future cross-machine workflows. | User accepted the target-local identity recommendation. | confirmed |
| FRQ-3 | Transfer evidence depth for v11 queue launchers | Roadmap framing | 3 | Provide machine-readable evidence for config identity, required files, workspace roots, payload expectations, environment prerequisites, schema compatibility, and verification status. Unsupported transfer handlers fail explicitly. | This is the direct v11 handoff and determines whether queue docs can say a workspace is proven equivalent. | User confirmed v12 should not implement concrete transfer handlers beyond explicit unsupported behavior. | confirmed |
| FRQ-4 | Exporter/importer protocol scope | FRQ-1 | 4 | Keep `RunExporter`/`RunImporter` minimal and core-owned; no external MLflow/DVC/W&B/static-report implementations; no automatic post-run dispatch. | Premature external-tool semantics would lock in wrong abstractions before plugin discovery. | User confirmed no external implementations for now. | confirmed |
| FRQ-5 | Resumable migrated-run readiness | FRQ-1, FRQ-2 | 5 | V12 should add importer result fields, manifest metadata, and hook interfaces that can report whether a migrated run is `historical_only`, `resume_candidate`, or `resume_unsupported`, with explicit blockers. It should not let the runner resume migrated imports until a later roadmap defines equivalence, rebasing, and authority-continuation rules. | This preserves future migration-resume extensibility without weakening v10 safety or inventing a partial live-resume path. | User confirmed readiness metadata and hooks are enough for v12. | confirmed |

## Functional Requirements

Confirmed functional requirements from roadmap framing, intent discovery,
capability triage, and functionality-agreement review.

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Export a completed run to a versioned bundle | none | Create manifest plus selected metadata/payload entries. | Safe archival and transfer. | Local completed runs, metadata-only by default. | `loom export` and Python API produce a bundle and summary. | Reads authoritative completed-run metadata and local materialized refs, then writes safe archive entries. | Run bundle export. | Unit/integration tests with synthetic completed runs. | confirmed |
| FR-2 | Inspect bundle without extraction | FR-1 | Read manifest and summaries from an archive. | Safe review before import. | No file extraction by default. | CLI/API show run, status, stages, artifacts, payload counts/sizes, warnings. | Validates manifest envelope and entry metadata. | Bundle inspect. | Tests with normal and unsafe bundle fixtures. | confirmed |
| FR-3 | Import bundle or offline evidence through a shared importer contract | FR-1, FR-2 | Validate evidence, safely materialize selected entries, write import metadata, optionally import accepted facts into authority, and mark/refresh catalog projections. | Restore/review/migrate completed runs without project code execution and without maintaining two import semantics. | Local run collections plus authority-backed import targets; imports remain terminal historical migrations in v12, with resumability represented only as readiness metadata and explicit blockers. Imported copies use target-local identity, with source `run_uri` and bundle/evidence identity preserved as provenance. | CLI/API report imported run target, source identity, provenance, warnings, and rejection diagnostics. | Rejects unsafe paths and collisions by default; verifies checksums when requested; preserves v10 offline-import validation semantics. | Bundle/offline import. | Temporary collection import tests plus offline-evidence importer regression tests. | confirmed |
| FR-4 | Record transfer-interface evidence | FR-1 | Produce portable evidence records for queue/delegated launch equivalence checks. | Closes v11 delegated workspace assumption gap. | Evidence and verification status, not full transport orchestration. | Queue/preflight surfaces can show proven/unproven transfer assumptions. | Records config identity, required files, workspace roots, payload expectations, environment prerequisites, schema compatibility, and verification evidence. | Queue transfer verification. | Unit tests for record serialization and queue-consumable evidence shape. | confirmed |
| FR-5 | Define minimal compatibility exporter/importer protocols | FR-1, FR-3 | Add `RunExporter`, `RunImporter`, and result models over completed metadata, bundle manifests, selected payload refs, and accepted offline evidence. | Future external-tool adapters and core migration paths need stable hooks. | Protocol and result records only; no external MLflow/DVC/W&B/static-report implementations. | Python users can call explicit exporters/importers; core CLI can wrap built-in bundle/offline importers. | Core validates importer/exporter results but does not dispatch automatically. | Compatibility exporters/importers. | Protocol contract tests with fake exporter and fake importer. | confirmed |
| FR-6 | Record resumable-migration readiness without enabling live resume | FR-3, FR-5 | Add manifest/import-result metadata and internal hook points for migration resume eligibility, target-store equivalence, artifact-ref rebasing, authority import policy, and planner reuse blockers. | Future versions need a stable place to attach the facts required for resumable migrated runs. | Interface and metadata only; runner/planner must still reject live resume from migrated imports unless a later policy says otherwise. | Import results show whether the run is historical-only, a future resume candidate, or unsupported for resume, with machine-readable blockers. | Importers compute or carry resume-readiness facts; continuation and runner surfaces keep migrated-live-resume disabled. | Resumable migration readiness. | Model tests plus import-result diagnostics asserting live resume remains unsupported. | confirmed |

## Behavior Baseline

Included functionality:

- Export terminal completed-run metadata and selected payload/log entries into a
  versioned local bundle.
- Inspect a bundle without extracting files.
- Import a bundle or offline evidence through a shared importer contract into a
  local run collection or authority-backed target.
- Use target-local identity for imported copies, while preserving source
  `run_uri`, source workspace/store metadata, and bundle/evidence identity in
  import provenance.
- Produce transfer-interface evidence records that v11 queue/delegated launch
  surfaces can cite.
- Define minimal `RunExporter` and `RunImporter` protocols and result records.
- Record resumable-migration readiness metadata and blockers without enabling
  migrated live resume.
- Report unsupported transfer handlers explicitly.

User-visible behavior:

- Python APIs and CLI commands can export, inspect, and import local bundles.
- Export reports bundle path, manifest summary, payload selection, warnings,
  and size/path facts.
- Inspect reports format, run identity, source identity, run status, stage and
  artifact summaries, payload counts/sizes, warnings, and optional checksum
  verification status without extraction.
- Import reports target run identity, source run identity, import provenance,
  imported record counts, materialized payload summary, catalog refresh/stale
  state, resume-readiness status, and rejection diagnostics.
- Queue/preflight surfaces can display proven, unproven, or unsupported
  transfer checks without parsing bundle internals.

Default behavior:

- Metadata-only export.
- Local archive using standard-library archive support.
- No project code execution during export, inspect, or import.
- No extraction during inspect.
- Import uses target-local identity, rejects target collisions, and records
  source identity in provenance.
- Unsupported transfer handlers fail explicitly.
- Migrated live resume remains disabled while readiness hooks report blockers.

Failure behavior and diagnostics:

- Confirmed failure families include non-terminal run, unsupported schema,
  active run changed during read, unsafe path, symlink surprise, missing
  payload, checksum mismatch, unexpected large payload, import collision,
  unsupported archive format, stale catalog state, unsupported transfer kind,
  invalid or incomplete offline evidence, and resume blocked for migrated
  imports.

Explicit deferrals:

- Concrete transfer handlers for network copy, SSH sync, remote object-store
  movement, or automatic workspace staging.
- Actual live resumability for migrated runs, including stage reuse from a
  different workspace/store, artifact URI rebasing, run identity remapping, and
  authority continuation from imported historical facts.
- External exporter/importer implementations.
- Automatic post-run dispatch.
- Signed/encrypted/deduplicated/cross-machine synchronized bundles.

Out-of-scope behavior:

- External service-specific exporters/importers.
- Automatic exporter dispatch after a run finishes.
- Concrete network, SSH, object-store, remote workspace, or automatic staging
  transfer handlers.
- Signed, encrypted, deduplicated, or cross-machine synchronized bundles.
- Domain-specific metric/report semantics.
- Actual live continuation or artifact reuse from migrated imports.

Context compaction/reset checkpoint:

- Checkpoint status: recorded after functionality and behavior confirmation.
- Notes path: `docs/roadmap/stage-12/planning.md`
- Resume instruction: reload this moved planning artifact, `docs/roadmap.md`
  stage 12, `docs/roadmap/stage-11/implementation-plan.md`,
  `docs/roadmap/stage-11/planning.md`, relevant feature docs, `docs/structure.md`,
  `.codex/prompts/roadmap-stage-design-agreement.md`, and
  `.codex/prompts/roadmap-stage-design-safety-review.md` before
  design-agreement review. Treat confirmed functionality and behavior as
  binding unless the user explicitly reopens it.
- Functionality and behavior reopened after checkpoint: not applicable

## Proposed Implementation Shape

Likely modules or packages:

- Pending design agreement. Early repo evidence points toward `loom.runs` for
  bundle/export/import public APIs, `loom.pipeline.stores` for authoritative
  metadata and materialized-ref inputs, `loom.io` or internal helpers for safe
  URI/path/archive handling, `loom.queue` for consuming transfer evidence, and
  `loom.cli` for command presentation.

Likely public classes, functions, or protocols:

- Pending design agreement.

Likely internal helpers:

- Pending design agreement.

Data flow:

- Pending design agreement.

Dependency direction:

- Pending design agreement.

Extension points and flexibility boundaries:

- Pending design agreement.

Compatibility constraints:

- Pending design agreement.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Bundle module ownership and public import path | Confirmed behavior | 1 | draft | Likely `loom.runs` owns public bundle APIs, with store and I/O helpers kept below it. | Determines import boundaries and future plugin/exporter routing. | Not ready for user discussion until behavior baseline is locked. | draft |
| DAQ-2 | Bundle manifest schema and compatibility policy | Confirmed behavior | 2 | draft | Versioned plain JSON manifest with strict unknown/unsupported schema behavior. | Durable archive compatibility depends on this. | Not ready for user discussion until behavior baseline is locked. | draft |
| DAQ-3 | Import identity and collision policy | FRQ-1 | 3 | draft | Reject collisions by default; record import provenance. | Affects catalog semantics and future cross-machine sync. | May need user feedback after requirement framing. | draft |
| DAQ-4 | Offline import refactor boundary | FRQ-1 | 4 | draft | Share importer contracts and validation/result models while preserving existing v10 offline import compatibility at public command/API boundaries. | Refactor could break current authority import semantics if too aggressive. | Needs design agreement after terminal/resumable import behavior is locked. | draft |
| DAQ-5 | Resumable migration readiness contract | FRQ-5 | 5 | draft | Add metadata/hook points for resume eligibility and blockers, but keep live migrated-resume disabled in v12. | Public import records and future planner behavior must not conflict. | Needs confirmation that deferring implementation is acceptable. | draft |
| DAQ-6 | Exporter/importer protocol breadth | FRQ-4 | 6 | draft | Minimal explicit protocols, no automatic dispatch, no external-tool semantics. | Prevents premature public API lock-in. | User already confirmed no external implementations; design pass should record this as recommendation unless new risks appear. | draft |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Bundle module ownership and public import path | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | pending |
| DAQ-2 | Bundle manifest schema and compatibility policy | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | pending |
| DAQ-3 | Import identity and collision policy | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | pending |
| DAQ-4 | Offline import refactor boundary | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | pending |
| DAQ-5 | Resumable migration readiness contract | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | pending |
| DAQ-6 | Exporter/importer protocol breadth | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | pending |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | pending | Pending | FR-1, FR-2, FR-3 | summarize later | pending |
| DAQ-2 | pending | Pending | FR-1, FR-2, FR-3 | summarize later | pending |
| DAQ-3 | pending | Pending | FR-3 | discuss later if still material | pending |
| DAQ-4 | pending | Pending | FRQ-1, FR-3 | discuss later if still material | pending |
| DAQ-5 | pending | Pending | FR-6 | discuss later if still material | pending |
| DAQ-6 | pending | Pending | FR-5 | summarize later | pending |

## Design Safety Review

| Finding | Affected decision or requirement | Refactor or compatibility risk | Recommended action | Status |
| --- | --- | --- | --- | --- |
| Design safety review has not run. | All material requirements and design decisions | Unknown until design-agreement queue is resolved. | Run the bounded design-safety review before phase shaping or implementation-plan drafting. | pending |

Gate result:

- Status: pending
- Reviewer: pending
- Blockers: none known at roadmap-framing startup
- Recorded recommendations: pending
- Accepted risks: pending
- Revisit triggers: pending

## Practical Design Notes

Public Python API surface:

- Pending design agreement. User direction now points to minimal `RunExporter`
  and `RunImporter` protocols plus built-in bundle/offline implementations or
  adapters only.

CLI surface:

- Pending design agreement. Roadmap names export, inspect, and import commands.

Persisted records and file layout:

- Pending design agreement. Roadmap requires a portable manifest with format
  version, entries, checksums, and payload selection metadata.

Import boundaries and dependencies:

- `loom.runs` should not bypass authority-backed completed-run read models when
  authoritative facts are available.
- `loom.cli` should remain a thin caller of public APIs.
- Core bundle behavior should not require external service, cloud, compression,
  exporter, plugin, or domain dependencies.

Failure modes and diagnostics:

- Confirmed baseline includes unsupported transfer kind, import collision,
  invalid or incomplete offline evidence, unsafe bundle path, checksum
  mismatch, non-terminal import source, active run changed during read,
  unexpected large payload, stale catalog state, unsupported archive format, and
  live-resume blocked for migrated imports.

Extension points and flexibility boundaries:

- Pending design agreement.

Maintainability assessment:

- Pending design agreement.

Extensibility assessment:

- Pending design agreement.

Flexibility and expansion assessment:

- Pending design agreement.

Scalability and future compatibility:

- Pending design agreement.

Resumable migrated-run readiness notes:

- Required public/result concepts for v12:
  - `RunImportPolicy` or equivalent policy value with import target,
    collision policy, checksum policy, materialization policy, and
    `resume_mode`.
  - `resume_mode` values should likely include `historical_only`,
    `resume_candidate`, and `resume_unsupported`. V12 should default to
    `historical_only` for executable behavior.
  - `RunImportResult` should expose source run identity, target run identity,
    import provenance, imported record counts, materialized payload summary,
    transfer evidence summary, and resume-readiness facts.
  - A `MigrationResumeReadiness` or equivalent record should carry
    machine-readable blockers instead of a boolean. Candidate blockers include
    unsupported source schema, unsupported target authority schema, run identity
    collision, unrebased artifact URI, missing payload, checksum mismatch,
    unverified config/pipeline/stage fingerprint equivalence, unavailable
    target store capability, imported historical-only policy, and non-terminal
    source evidence.
  - Bundle manifests should preserve the facts later resume needs: source
    workspace/store identity, source authority schema, run status, config and
    pipeline fingerprints, stage fingerprints, artifact refs and checksums,
    materialized-ref verification, payload selection, and any run-uri mapping.
- Required internal hooks for future implementation:
  - validate source evidence and target authority/store compatibility;
  - plan run identity mapping from source to target;
  - plan artifact/materialized-ref rebasing into the target collection or store;
  - validate fingerprint and payload equivalence after materialization;
  - import authority facts through the authority boundary with explicit import
    provenance;
  - expose resume-readiness to planner/preflight without making the planner
    parse bundle internals.
- Behavior required before migrated live resume can be enabled in a later
  version:
  - The planner must treat imported facts as reusable only after target-side
    authority facts, materialized refs, fingerprints, and checksums are proven
    equivalent to the current resolved pipeline.
  - Imported active leases, active attempts, and submitted operations must not
    become live work automatically. Any resumed or rerun work needs fresh
    authority attempts and fresh leases in the target authority.
  - Source `file://` artifact refs cannot be trusted on the target unless they
    are rebased to target-local materialization or proven portable by a later
    remote-store contract.
  - Import provenance must remain visible so diagnostics can distinguish
    native target runs, historical imports, and future resume-capable imports.
  - If any required equivalence fact is absent, resume must fail closed or fall
    back to ordinary rerun planning rather than silently reusing migrated
    artifacts.
- Recommended v12 boundary:
  - Define the policy/result/readiness records and hook locations.
  - Keep imported runs historical/non-resumable by default.
  - If a user explicitly asks to resume a migrated import, return a structured
    unsupported/resume-blocked diagnostic that cites the missing later policy
    instead of attempting best-effort reuse.

Accepted debt:

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| V12 likely starts with local archive/import only. | Roadmap defers remote store operations, encryption, deduplication, and cross-machine synchronization. | Remote store contract/operations or real cross-machine transfer requirements land. |
| Exporter protocol likely exists before plugin loading. | V14 owns plugin discovery after the v12 protocol exists. | Plugin discovery implementation needs the protocol widened for concrete adapters. |
| Offline import refactor may need compatibility shims. | V10 already shipped strict offline import commands and authority API routes. | Shared importer work proves the old route can be replaced without losing diagnostics or provenance. |
| Resume-readiness hooks may ship before behavior. | They reserve the correct public result fields and extension points without pretending migrated live resume is safe. | A later roadmap implements target-store equivalence, artifact rebasing, and authority continuation policy. |

## Examples And Demonstrations

| Example | Behavior demonstrated | Loom context | Required docs/tests | Status |
| --- | --- | --- | --- | --- |
| Metadata-only completed-run export | Conservative archive behavior and manifest creation | Synthetic terminal run with authoritative metadata | Unit/integration export tests; CLI/API docs | draft |
| Bundle inspection without extraction | Safe review and summary output | Bundle fixture with manifest and payload-selection metadata | Inspect tests and CLI JSON/text output coverage | draft |
| Safe import into temporary collection | Manifest validation, safe path handling, catalog stale marking | Temporary local run collection | Import tests with collision and unsafe path cases | draft |
| Offline evidence import through shared importer | Existing v10 evidence imports use the same importer/result semantics as bundle import | Offline evidence fixture from current tests | Regression tests around strict rejection, replay events, and provenance | draft |
| Resumable migration readiness report | Import result explains why migrated live resume is blocked or potentially candidate-only | Bundle/offline evidence import fixture | Model and diagnostic tests; docs showing deferral boundary | draft |
| Delegated transfer evidence | Proven/unproven workspace checks for queue launch contracts | Queue launch contract or preflight fixture | Serialization/contract test for evidence shape | draft |
| Fake compatibility exporter/importer | `RunExporter` and `RunImporter` result models without external tools | Fake exporter over completed metadata and manifest ref; fake importer over manifest/evidence | Contract test | draft |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import boundaries | Bundle APIs are import-light and do not import CLI, queue controllers, plugins, external tools, or project code at import time. | Package tests | Package | `tests/package` | draft |
| Manifest models | Schema versioning, entry validation, checksum fields, payload selection metadata. | Unit tests | Unit | `tests/unit/loom/runs` or equivalent | draft |
| Export | Completed-run metadata projection, metadata-only default, optional artifact/log payload inclusion, size/path reporting. | Unit and integration tests | Unit/integration | `tests/unit`, `tests/integration` | draft |
| Safety | Path traversal, symlink, partially written run, missing payload, checksum mismatch, and large unexpected payload handling. | Focused unit/integration tests | Unit/integration | `tests/unit`, `tests/integration` | draft |
| Inspect | Manifest read and summary without extraction. | Unit/CLI tests | Unit/contract/integration | `tests/contracts`, `tests/integration` | draft |
| Import | Safe extraction into temporary collection, collision rejection, checksum verification, catalog stale marking or refresh. | Integration tests | Integration | `tests/integration` | draft |
| Offline import alignment | Existing offline evidence import validation, rejection diagnostics, replay events, and historical provenance survive through shared importer alignment. | Unit/integration regression tests | Unit/integration | `tests/unit/loom/authority`, `tests/integration/authority` | draft |
| Resumable migration readiness | Importer result carries eligibility/blocker facts, and runner/planner surfaces still reject migrated live resume. | Unit/contract tests | Unit/contract | `tests/unit`, `tests/contracts` | draft |
| Transfer evidence | Queue-consumable verification record shape and status semantics. | Contract tests | Contract | `tests/contracts` | draft |
| Exporter/importer protocols | Fake exporter/importer return structured result records over completed metadata, bundle refs, and offline evidence refs. | Contract tests | Contract | `tests/contracts` | draft |
| CLI | Thin text/JSON wrappers for export, inspect, import. | CLI integration tests | Integration/e2e | `tests/integration` and limited `tests/e2e` | draft |
| PR gate | Full repository validation before PR preparation. | Required checks | Make targets | `make validate-pr`; `make test-summary` | draft |

## Phase Sketch

Phase sketch is intentionally deferred until functionality, behavior, design
agreement, design-safety review, examples, and validation strategy are confirmed.

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

- Package: TBD
- Unit: TBD
- Contract: TBD
- Integration: TBD
- E2E: TBD
- Opt-in: TBD

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

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Roadmap framing, intent discovery, capability triage, functionality agreement, and behavior baseline are confirmed. | pass | None. |
| Requirement-to-design traceability | Context checkpoint is recorded and draft design queue exists, but design agreement has not started after reset/resume. | block | Complete design agreement after context reset/resume. |
| Design-safety review completed | Not run. | block | Run bounded design-safety review before phase shaping. |
| Example-to-validation traceability | Draft examples and validation strategy recorded. | block | Confirm after behavior/design decisions are locked. |
| Phase-shaping readiness | Phase sketch not started. | block | Shape phases after design-safety review. |
| Unresolved blocked or needs-discussion functionality or design decisions | No functionality blockers remain; draft design decisions are pending classification and review. | block | Resolve the design-agreement queue after context reset/resume. |

Readiness result:

- Status: pending
- Implementation-plan drafting blockers:
  - Context reset/resume, design agreement, design-safety review,
    examples/validation, and phase shaping remain open.
  - V11 Phase 9 status must be refreshed before implementation-plan drafting.
- Accepted risks: pending
- Assumptions to carry forward:
  - V12 remains local, conservative, and dependency-light unless user direction
    changes during planning.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the v12 briefing before capability triage starts? | Roadmap framing | No clarifying questions before proceeding. | closed |
| What should v12 optimize for relative to the roadmap: safe archive/import, v11 transfer evidence, external exporter compatibility, or a different priority? | Roadmap framing and intent discovery | Optimize first for safe conservative archive/import plus concrete transfer evidence; keep exporter hooks minimal. | closed |
| Should implementation-plan drafting wait for v11 Phase 9 to merge, or may it draft with an explicit Phase 9 refresh dependency? | Handoff and implementation planning | Planning can continue now; implementation-plan draft should refresh against v11 Phase 9 before naming final CLI/preflight integration points. | assumed default |
| Should bundle/offline imports remain terminal historical migrations in v12, or should v12 reopen resumable live continuation semantics after import? | Functionality agreement and import behavior | Preserve v10 historical/non-resumable import semantics; record resume-readiness metadata and blockers only; treat live continuation after import as future work unless explicitly reopened. | closed |
| Should v12 provide resume-readiness metadata and hooks while keeping actual migrated live resume unsupported? | Functionality agreement and design agreement | Yes: add explicit eligibility/blocker records and extension hooks, but do not let the runner resume migrated imports in v12. | closed |
| When importing a bundle into a different workspace or run collection, should Loom preserve the source `run_uri` as identity, or allocate a target-local identity while preserving the source identity as provenance? | Functionality agreement and import behavior | Allocate or use a target-local run identity for the imported copy, reject target collisions, and preserve the source `run_uri` and bundle/evidence identity in import provenance. | closed |

## Handoff Notes

Implementation-plan draft inputs:

- Not ready. Use these notes only after all stage gates are confirmed and the
  user explicitly confirms they are happy with the planning notes.

Design-safety review result:

- Pending.

Validation and phase-shaping inputs:

- Pending.

Plan-quality-gate risks:

- Design must preserve the confirmed target-local import identity, collision
  rejection, and source-provenance behavior through concrete public models.
- Design must preserve the confirmed terminal/historical-only import boundary
  while exposing resume-readiness blockers without enabling live continuation.
- Potential public API overreach in `RunExporter`/`RunImporter` before plugin
  discovery and remote stores.
- Potential drift if v11 Phase 9 changes queue CLI/preflight surfaces.

Assumptions to carry forward:

- V12 should keep Loom domain-neutral.
- V12 should use standard-library archive support by default.
- V12 should not execute project code during export, inspect, or import.
- V12 should preserve authority truth versus local materialization boundaries.
- V12 should align bundle import/export with v10 offline import through shared
  importer/exporter contracts.
