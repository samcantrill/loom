# Roadmap v12 Planning Notes: Run Bundles, Transfer, And Exporters

## Metadata

- Roadmap version: v12
- Source roadmap: `docs/roadmap.md`
- Previous version status: `docs/roadmap/stage-11/implementation-plan.md` has
  passed its plan quality gate and now records V11 Phases 1 through 9 as merged
  on `develop`. Phase 9, the operational UX, minimal CLI wrapper, docs, and
  hardening phase, merged on 2026-05-14. V12 planning may proceed from the
  locked v11 queue assumptions, and implementation-plan drafting must use the
  final v11 queue CLI/preflight surfaces rather than the older startup
  assumption that Phase 9 was pending.
- Planning notes status: confirmed; implementation-plan drafting ready
- Current discussion stage: final planning confirmed; implementation-plan draft
  in progress.
- Stage gates:
  - Roadmap framing: confirmed
  - Intent discovery: confirmed
  - Capability triage and candidate functional requirements: confirmed
  - Functionality agreement review: confirmed
  - Functionality and behavior confirmation: confirmed
  - Context compaction/reset checkpoint: completed
  - Design agreement review: confirmed
  - Design safety review: completed
  - Examples and validation strategy: confirmed
  - Phase shaping: confirmed
  - Implementation readiness: confirmed
  - Handoff: ready
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
  - None from design-safety review.
  - Implementation-plan drafting must carry the refreshed v11 Phase 9 state,
    name bundle CLI/preflight integration points against the now-current
    `loom queue` and `loom runs` command surfaces, and preserve the revised
    portable-run exchange boundary: local bundles and v10 offline evidence are
    concrete Loom adapters over shared import/export contracts, not one
    collapsed storage format.

## Source Evidence

| Source | Relevant content | Used for | Notes |
| --- | --- | --- | --- |
| `docs/roadmap.md` | V12 provides safe run export, transfer-interface verification, bundle inspect/import, and compatibility exporter contracts with portable manifests. | roadmap scope | This is the baseline scope for planning. |
| `docs/roadmap.md` | V11 defers full run bundle transport, remote artifact payload movement, and proof of complete remote workspace equivalence to v12. | prerequisite and dependency gap | V12 must close the queue/delegated-launch evidence gap without redesigning queue scheduling. |
| `docs/roadmap/stage-11/implementation-plan.md` | V11 keeps queue policy separate from authority truth, records launch contracts, leaves delegated SLURM launch on shared/pre-staged workspace assumptions until bundle transport exists, and now records Phase 9 merged on 2026-05-14 with the thin queue operational CLI landed. | v12 handoff and current CLI context | V12 should provide reusable verification records that queue adapters can cite rather than making the queue parse bundle internals; bundle command naming should account for the current `loom queue` and `loom runs` surfaces. |
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
| Prior and adjacent plans | `docs/roadmap/stage-11/implementation-plan.md`, `docs/roadmap/stage-11/planning.md`, `docs/roadmap/stage-10/planning.md` | V11 leaves bundle-backed remote equivalence for v12; v10/v11 authority surfaces require strict source-of-truth separation; V11 Phase 9 is now merged and the queue operational CLI exists. | Implementation-plan drafting should use the current v11 CLI/preflight surface instead of the earlier pending-Phase-9 assumption. |
| Feature docs | `run-catalog.md`, `run-store.md`, `artifacts.md`, `io.md`, `cli.md`, `testing.md`, targeted `remote-stores.md` export integration and `plugins.md` protocol context | Feature docs already place export/import under run catalog, payload refs under artifacts/stores, URI/archive behavior under I/O, command presentation under CLI, future remote refs as metadata-only by default, and plugin loading after explicit discovery. | None for design-safety review. |
| Source and tests | `src/loom/runs/*`, `src/loom/cli/runs.py`, `src/loom/pipeline/stores/materialization_read_models.py`, `src/loom/queue/models.py`, `src/loom/authority/offline_import.py`, `src/loom/pipeline/offline_evidence.py`, run-catalog, queue, and offline-import contract/integration tests | Catalog list/diff, completed-run bundle metadata, queue launch verification, strict offline-evidence import seams, and thin CLI command patterns exist; bundle/export/import and generic importer/exporter modules do not. | Design-safety review should pressure-test authority/import coupling and public protocol breadth. |

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

- V12 is Loom's first portable-run exchange and compatibility-export version.
  It defines shared import/export contracts for completed run records, provides
  a local bundle archive/manifest adapter, aligns v10 offline evidence as a
  Loom-specific adapter over the same result semantics, lets users inspect and
  import local bundles safely, records transfer-interface evidence for queued
  or delegated launches, and defines small importer/exporter protocols that
  later plugins or providers can implement.

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
  treat that as a Loom-specific adapter over the shared portable-run import
  result semantics, not as a second import concept and not as a bundle archive
  format.
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

- Public Python value models for a portable run exchange core: source identity,
  target identity policy, selected entries, payload refs, diagnostics,
  import/export results, transfer verification records, resume-readiness facts,
  and minimal `RunExporter` and `RunImporter` protocols.
- Local bundle-specific value models for bundle manifests, manifest entries,
  payload selection policy, bundle inspection results, and archive safety
  diagnostics.
- Public operations for exporting a completed run through a concrete adapter,
  inspecting a local bundle without extraction, importing into a local run
  collection, and importing accepted run evidence into authority through a
  shared importer contract.
- A versioned manifest document inside every local bundle with format version,
  source run identity, authority schema facts, entry records, checksums, payload
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

- Confirmed. Design agreement records repo-supported recommendations for
  module ownership, manifest compatibility, archive safety, target-local import
  identity, offline-import adapter boundaries, transfer evidence ownership,
  resume-readiness records, importer/exporter protocol breadth, and CLI refresh
  dependency. No high-impact design decision remains in `needs discussion` or
  `blocked` status before design-safety review.

Design-safety review follow-up:

- Completed. The bounded review upheld DAQ-1 through DAQ-8 as recorded
  recommendations and refined DAQ-9 from a pending-v11 refresh dependency into
  a current-surface implementation-plan obligation; the later protocol revision
  added DAQ-10 to keep portable-run exchange records as the base abstraction,
  with local bundles and v10 offline evidence as separate adapters. No blocker
  or needs-discussion decision remains. Residual risks are import-light neutral
  model placement for authority/offline import, narrow queue consumption of
  transfer evidence, conservative archive safety, and future widening of the
  importer/exporter protocols after stage 14 or real adapters.

## Stage Readbacks

| Stage | Locked decisions | Defaults | Open questions | Next focus |
| --- | --- | --- | --- | --- |
| Roadmap framing | Startup briefing confirmed from roadmap, feature docs, v11 handoff, and current source seams. Planning priority is safe conservative archive/import first, concrete v11 transfer evidence second, and minimal exporter hooks third. | Metadata-only local export by default; no project code execution; inspect without extraction; exporter hooks stay minimal. | None for framing. | Intent discovery. |
| Intent discovery | Bundles should align with offline import; unsupported transfer kinds fail explicitly; v12 should introduce both `RunExporter` and `RunImporter`; no external implementations ship now; v12 adds resume-readiness hooks but not migrated live resume. | Preserve v10 strict import safety and historical/non-resumable provenance for executable behavior; add resume-readiness metadata/hooks without enabling live continuation. | None for intent discovery. | Capability triage. |
| Capability triage and candidate functional requirements | Include bundle manifests, metadata-only export, explicit payload/log flags, transfer evidence, inspect without extraction, safe import, minimal exporter/importer protocols, offline-import alignment, resumable-readiness hooks, and unsupported-transfer diagnostics. Defer concrete transfer handlers, external implementations, automatic dispatch, signing/encryption/dedupe/sync, and live migrated resume. | Conservative local archive/import first; queue transfer evidence second; minimal exporter/importer hooks third. | None. | Confirm behavior baseline. |
| Functionality agreement review | Shared importer/exporter contract is accepted; v10 strict import safety is preserved; imported runs use target-local identity with source identity in provenance; imported runs remain terminal historical/non-resumable in v12. | Reject collisions by default; do not execute project code; record resume-readiness blockers instead of enabling live migrated resume. | None. | Lock behavior baseline. |
| Functionality and behavior confirmation | Confirmed export, inspect, import, transfer evidence, importer/exporter protocols, readiness metadata, explicit unsupported-transfer behavior, and deferrals. | Metadata-only local archive by default; no project code execution; no inspect extraction; target-local import identity with source provenance; collision rejection; migrated live resume disabled. | None. | Proceed to design agreement after context reset/resume. |
| Context compaction/reset checkpoint | This planning artifact has moved to `docs/roadmap/stage-12/planning.md`; confirmed functionality and behavior are now the source of truth. | Resume design agreement from the moved artifact and do not reopen requirements unless explicitly requested. | None. | Completed for design agreement. |
| Design agreement review | Confirmed module ownership, manifest compatibility, archive safety, target-local import identity, offline-import adapter boundary, transfer evidence ownership, resume-readiness contract, protocol breadth, CLI refresh dependency, and portable-run exchange adapter boundary as recorded recommendations. | Keep public bundle/exchange APIs in `loom.runs` or an import-light adjacent module; keep stores/authority/queue boundaries explicit; use plain data for persisted records and transfer evidence; do not ship external provider adapters or live migrated resume. | None. | Run bounded design-safety review. |
| Design safety review | Completed with DAQ-1 through DAQ-8 upheld, DAQ-9 refined to use the now-current v11 Phase 9 CLI/preflight surface, and DAQ-10 added as a protocol-revision recommendation. | Keep shared importer/exporter models import-light; keep portable-run exchange adapter-neutral; keep queue consumption plain-data only; keep archive safety fail-closed; keep migrated live resume disabled. | None. | Confirm examples and validation strategy. |
| Examples and validation strategy | Confirmed metadata-only export, inspect, safe import, offline-import alignment, resume-readiness, transfer evidence, fake importer/exporter, unsupported provider behavior, package/import-boundary, CLI, and PR-gate evidence. | Default validation stays local and deterministic; no real remote stores, external services, plugins, network, or clusters in default tests. | None. | Record phase shaping. |
| Phase shaping | Confirmed five-phase split: portable exchange/model/manifest contracts; export/archive/inspect; import/offline alignment/readiness; transfer evidence and importer/exporter protocols; CLI/docs/hardening/final validation. | Keep protocol abstraction, archive safety, and import-boundary risk front-loaded; defer CLI exact naming to implementation-plan refresh against current CLI surface. | None. | Final planning confirmation. |
| Implementation readiness | Requirements, behavior, design agreement, design-safety review, examples/validation, phase shaping, and final planning confirmation are confirmed. | Draft implementation plan from this artifact. | None. | Implementation-plan draft. |
| Handoff | Ready. User confirmed the planning artifact and requested implementation-plan drafting from it. | Use this planning artifact as the primary source for the implementation-plan draft. | None. | Draft `docs/roadmap/stage-12/implementation-plan.md`. |

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
| FRQ-1 | Shared portable-run exchange contract across bundles and offline evidence | Roadmap framing, intent discovery | 1 | Introduce shared portable-run import/export records and `RunExporter`/`RunImporter` protocols. Treat the local bundle archive and v10 offline evidence as concrete Loom adapters over those records. Do not collapse offline evidence into the bundle storage format, and do not delete the v10 import safety semantics; refactor or adapterize them behind the shared importer/result model. Imported runs stay historical/non-resumable in v12, with resume-readiness metadata and blockers recorded for later work. | Prevents two competing migration/import concepts before remote stores and cross-workspace workflows arrive while avoiding a bundle-shaped abstraction that would constrain later providers. | Prior intent discovery resolved the live-resume branch, and the protocol revision clarifies that v12 should add shared exchange contracts plus readiness hooks but not implement migrated live continuation. | confirmed with protocol revision |
| FRQ-2 | Bundle/import collision and identity policy | FRQ-1 | 2 | Allocate or use a target-local run identity for the imported copy; preserve source run metadata, source `run_uri`, and bundle/evidence identity in import provenance; reject target collisions by default; do not silently overwrite or execute project code. | Import identity affects catalog behavior, authority mutation, and future cross-machine workflows. | User accepted the target-local identity recommendation. | confirmed |
| FRQ-3 | Transfer evidence depth for v11 queue launchers | Roadmap framing | 3 | Provide machine-readable evidence for config identity, required files, workspace roots, payload expectations, environment prerequisites, schema compatibility, and verification status. Unsupported transfer handlers fail explicitly. | This is the direct v11 handoff and determines whether queue docs can say a workspace is proven equivalent. | User confirmed v12 should not implement concrete transfer handlers beyond explicit unsupported behavior. | confirmed |
| FRQ-4 | Exporter/importer protocol scope | FRQ-1 | 4 | Keep `RunExporter`/`RunImporter` minimal and core-owned; no external MLflow/DVC/W&B/static-report implementations; no automatic post-run dispatch. | Premature external-tool semantics would lock in wrong abstractions before plugin discovery. | User confirmed no external implementations for now. | confirmed |
| FRQ-5 | Resumable migrated-run readiness | FRQ-1, FRQ-2 | 5 | V12 should add importer result fields, manifest metadata, and hook interfaces that can report whether a migrated run is `historical_only`, `resume_candidate`, or `resume_unsupported`, with explicit blockers. It should not let the runner resume migrated imports until a later roadmap defines equivalence, rebasing, and authority-continuation rules. | This preserves future migration-resume extensibility without weakening v10 safety or inventing a partial live-resume path. | User confirmed readiness metadata and hooks are enough for v12. | confirmed |

## Functional Requirements

Confirmed functional requirements from roadmap framing, intent discovery,
capability triage, and functionality-agreement review.

| ID | Requirement | Depends on | What | Why | Scope | User-visible behavior | System behavior | Capability enabled | Validation idea | Decision/status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FR-1 | Export a completed run through the portable-run exchange contract to a versioned local bundle | none | Create shared exchange records, then materialize them through the local bundle adapter as a manifest plus selected metadata/payload entries. | Safe archival and transfer without making the bundle archive the only provider shape. | Local completed runs, metadata-only by default; local bundle is the first concrete adapter. | `loom export` and Python API produce a bundle and summary. | Reads authoritative completed-run metadata and local materialized refs, builds shared export records, then writes safe archive entries through the local bundle adapter. | Run bundle export and base exchange export. | Unit/integration tests with synthetic completed runs plus contract tests for shared export result shape. | confirmed with protocol revision |
| FR-2 | Inspect bundle without extraction | FR-1 | Read manifest and summaries from an archive. | Safe review before import. | No file extraction by default. | CLI/API show run, status, stages, artifacts, payload counts/sizes, warnings. | Validates manifest envelope and entry metadata. | Bundle inspect. | Tests with normal and unsafe bundle fixtures. | confirmed |
| FR-3 | Import bundle or offline evidence through a shared portable-run importer contract | FR-1, FR-2 | Validate adapter-specific evidence, convert it into shared portable-run import records, safely materialize selected entries, write import metadata, optionally import accepted facts into authority, and mark/refresh catalog projections. | Restore/review/migrate completed runs without project code execution and without maintaining two import semantics or forcing every provider into the local bundle archive shape. | Local run collections plus authority-backed import targets; local bundle and v10 offline evidence are first-party adapters; imports remain terminal historical migrations in v12, with resumability represented only as readiness metadata and explicit blockers. Imported copies use target-local identity, with source `run_uri` and bundle/evidence identity preserved as provenance. | CLI/API report imported run target, source identity, adapter/source identity, provenance, warnings, and rejection diagnostics. | Rejects unsafe paths and collisions by default; verifies checksums when requested; preserves v10 offline-import validation semantics; provider/transport handlers not implemented in v12 fail explicitly. | Bundle/offline import over base exchange import. | Temporary collection import tests, shared importer contract tests, unsupported-adapter tests, and offline-evidence importer regression tests. | confirmed with protocol revision |
| FR-4 | Record transfer-interface evidence | FR-1 | Produce portable evidence records for queue/delegated launch equivalence checks. | Closes v11 delegated workspace assumption gap. | Evidence and verification status, not full transport orchestration. | Queue/preflight surfaces can show proven/unproven transfer assumptions. | Records config identity, required files, workspace roots, payload expectations, environment prerequisites, schema compatibility, and verification evidence. | Queue transfer verification. | Unit tests for record serialization and queue-consumable evidence shape. | confirmed |
| FR-5 | Define minimal compatibility exporter/importer protocols | FR-1, FR-3 | Add `RunExporter`, `RunImporter`, and result models over completed metadata, portable-run exchange records, bundle manifests, selected payload refs, and accepted offline evidence. | Future external-tool adapters and core migration paths need stable hooks that are not bundle-archive-specific. | Protocol and result records only; local bundle and offline-evidence adapters are first-party; no external MLflow/DVC/W&B/static-report implementations. | Python users can call explicit exporters/importers; core CLI can wrap built-in bundle/offline importers. | Core validates importer/exporter results but does not dispatch automatically; unimplemented provider adapters raise `NotImplementedError` or return structured unsupported diagnostics. | Compatibility exporters/importers. | Protocol contract tests with fake exporter/importer plus unsupported-adapter behavior. | confirmed with protocol revision |
| FR-6 | Record resumable-migration readiness without enabling live resume | FR-3, FR-5 | Add manifest/import-result metadata and internal hook points for migration resume eligibility, target-store equivalence, artifact-ref rebasing, authority import policy, and planner reuse blockers. | Future versions need a stable place to attach the facts required for resumable migrated runs. | Interface and metadata only; runner/planner must still reject live resume from migrated imports unless a later policy says otherwise. | Import results show whether the run is historical-only, a future resume candidate, or unsupported for resume, with machine-readable blockers. | Importers compute or carry resume-readiness facts; continuation and runner surfaces keep migrated-live-resume disabled. | Resumable migration readiness. | Model tests plus import-result diagnostics asserting live resume remains unsupported. | confirmed |

## Behavior Baseline

Included functionality:

- Define a shared portable-run exchange contract for completed-run import and
  export, with local bundle archives and v10 offline evidence treated as
  concrete Loom adapters over shared result semantics.
- Export terminal completed-run metadata and selected payload/log entries into a
  versioned local bundle through the local bundle adapter.
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
- Python APIs can use the same import/export result protocol for local bundle
  adapters and v10 offline-evidence adapters.
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

- The portable-run exchange contract is the base abstraction; local bundles are
  the first concrete transport/storage adapter, not the whole abstraction.
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
- Provider-specific adapters beyond the first-party local bundle adapter and
  v10 offline-evidence adapter. Deferred adapters should have reserved
  extension points and explicit unsupported diagnostics or `NotImplementedError`
  behavior in v12.
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

- `loom.runs` owns the public bundle, import, inspect, transfer-evidence, and
  compatibility importer/exporter surface, extending the current run-catalog
  facade without making the catalog sidecar authoritative.
- `loom.runs.models` or adjacent public `loom.runs` modules own immutable value
  models for portable-run exchange records, bundle manifests, entries, payload
  selection, inspection results, import/export policy/results, transfer
  verification records, and migration-readiness facts.
- `loom.runs` private helpers own archive read/write safety, manifest assembly,
  manifest validation, payload selection, checksum verification, local
  collection import, and catalog stale/refresh handling.
- The local bundle adapter owns archive and manifest materialization. The v10
  offline-evidence adapter owns conversion from accepted offline evidence into
  the same portable-run import result semantics while preserving authority
  diagnostics.
- `loom.pipeline.stores.materialization_read_models` remains the lower-layer
  authoritative metadata and materialized-ref input seam. It may grow narrow
  read options or projection facts, but it must not own archive formats,
  bundle import, exporter dispatch, or catalog side effects.
- `loom.authority.offline_import` stays the authority-specific import adapter
  for v10 offline evidence and preserves the existing public diagnostics and
  API behavior while sharing neutral importer/result models where practical.
- `loom.queue` records or consumes transfer verification as plain structured
  data in existing launch-contract and delegated-verification fields; queue
  core does not own bundle internals or bundle archive parsing.
- `loom.cli` adds thin command presentation over public Python APIs against the
  current v11 Phase 9 command surface.

Likely public classes, functions, or protocols:

- `PortableRunExportRecord`, `PortableRunImportRecord`,
  `PortableRunSourceIdentity`, `PortableRunTargetIdentityPolicy`, and
  adapter-neutral diagnostic/result envelopes, or equivalent names chosen
  during implementation-plan drafting.
- `RunBundleManifest`, `RunBundleEntry`, `RunBundleEntryKind`, and
  `RunBundleFormatVersion` or equivalent manifest/version value objects.
- `RunBundleExportOptions`, `RunBundleExportResult`,
  `RunBundleInspection`, `RunBundleImportPolicy`, `RunBundleImportResult`, and
  diagnostic/result envelopes that remain plain-data serializable.
- `TransferVerificationRecord`, `TransferVerificationCheck`, and status values
  for `proven`, `unproven`, and `unsupported`.
- `MigrationResumeReadiness` with blocker codes instead of a boolean.
- Minimal `RunExporter` and `RunImporter` protocols plus local bundle,
  offline-evidence, fake, and unsupported-adapter implementations for contract
  tests; no service-specific implementations ship in v12.
- `RunCatalog` grows convenience methods or public free functions for export,
  inspect, and import while preserving existing index/list/diff behavior.

Likely internal helpers:

- Archive helpers built on standard-library tar/gzip support with explicit
  normalized member paths, path traversal rejection, symlink policy, size
  accounting, and checksum verification.
- Manifest builders that consume `CompletedRunBundleMetadata` and selected
  `MaterializedRef` records without loading artifact payload semantics.
- Adapter helpers that convert completed-run store read models, local bundle
  manifests, and v10 offline evidence into shared portable-run exchange records
  without making bundle manifests the required source shape for every provider.
- Local import planners that allocate or accept target-local run identity,
  detect collisions before extraction, stage into a temporary directory, and
  commit only after validation succeeds.
- Adapter helpers that map existing offline-evidence validation results into
  neutral importer diagnostics without weakening v10 authority import policy.
- CLI formatting helpers for text/JSON summaries; CLI handlers remain outside
  lower layers.

Data flow:

- Export reads authoritative completed-run metadata through store read models,
  collects local materialized refs when requested, builds portable-run export
  records, passes them to the local bundle adapter, writes selected entries to a
  safe archive, and returns a summary/result.
- Inspect opens only the archive manifest and entry metadata, optionally
  verifies checksums, and never extracts into the current working directory.
- Import validates the adapter-specific source, converts bundle manifests or
  offline evidence into shared portable-run import records, resolves
  target-local identity, rejects collisions, stages safe entries, writes import
  provenance and catalog/authority-visible metadata, refreshes or marks catalog
  state, and returns diagnostics plus resume-readiness facts.
- Queue/delegated launchers reference transfer verification records as
  serialized evidence rather than interpreting bundle members.

Dependency direction:

- `loom.runs` may depend on public foundation, serialization, I/O URI helpers,
  and run-store read models.
- `loom.runs` must not import `loom.cli`, queue controllers, concrete
  executors, plugin discovery, optional external clients, project code, or
  artifact payload codecs for default export/import/inspect behavior.
- Store, execution, executor, and queue authority layers must not depend on
  bundle archive internals. Queue handoff uses plain-data evidence to avoid
  coupling.
- Authority import code may adapt to neutral importer/result records, but
  archive/local collection import must not mutate authority state except
  through explicit authority import adapters.

Extension points and flexibility boundaries:

- `RunExporter`/`RunImporter` are explicit callable protocols, not automatic
  plugin-discovery or event-sink dispatch points in v12.
- The base protocol is adapter-neutral portable-run exchange, not the local
  bundle archive format. Bundles and offline evidence are first-party adapters;
  future providers should implement the same importer/exporter protocols rather
  than inherit bundle storage assumptions.
- Manifest extension fields preserve opaque external or remote refs as
  metadata only until the stage 15 external artifact interface exists.
- Transfer verification records allow future concrete transfer handlers, but
  unsupported handlers fail explicitly in v12.
- Deferred provider, transport, signing, encryption, dedupe, and remote
  materialization hooks may exist as abstract interfaces only when they have
  clear result and diagnostic contracts; their runtime behavior must raise
  `NotImplementedError` or return structured unsupported diagnostics in v12.
- Migration-readiness records reserve future live-resume inputs without making
  imported historical facts executable.

Compatibility constraints:

- Bundle manifests are versioned, plain JSON, and strict at the top-level
  format/version boundary. Unsupported versions fail with structured
  diagnostics.
- Unknown future data is allowed only inside explicit extension/metadata
  fields, so v12 does not accidentally bless backend-specific semantics.
- Import keeps target-local identity and source provenance separate.
- Existing v10 offline import public behavior and diagnostics remain
  compatible unless implementation-plan review explicitly accepts a migration.
- CLI command names and preflight integration must be selected against the
  current v11 Phase 9 surface during implementation-plan drafting.

## Design Agreement Queue

| ID | Decision | Depends on | Resolution order | Classification | Recommended answer | Why it matters | Why user input is needed | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Bundle module ownership and public import path | Confirmed behavior | 1 | recorded recommendation | `loom.runs` owns public bundle APIs and result models; store read models stay below it; CLI remains presentation only. | Determines import boundaries and future exporter/plugin routing. | Repo structure and run-catalog feature docs give a clear recommendation. | confirmed |
| DAQ-2 | Bundle manifest schema and compatibility policy | DAQ-1 | 2 | recorded recommendation | Use versioned plain JSON with strict format/version handling, explicit entries/checksums/payload selection, and extension fields for opaque external refs only. | Durable archive compatibility and later remote-ref preservation depend on this shape. | Roadmap and feature docs give a clear recommendation. | confirmed |
| DAQ-3 | Archive, path-safety, and payload-selection boundary | DAQ-2 | 3 | recorded recommendation | Use standard-library local archives, metadata-only by default, explicit payload/log flags, normalized member paths, collision-safe staging, and checksum/size diagnostics. | This is the main data-loss and unsafe-extraction risk surface. | Confirmed behavior and feature docs already lock the safety boundary. | confirmed |
| DAQ-4 | Import identity and collision policy | FRQ-2 | 4 | recorded recommendation | Imported copies use target-local identity, source identity stays in provenance, and target collisions reject by default. | Affects catalog semantics, authority imports, and future cross-workspace migration. | User accepted this requirement-level decision. | confirmed |
| DAQ-5 | Offline import adapter boundary | FRQ-1, DAQ-4 | 5 | recorded recommendation | Share neutral importer/result models where practical, but keep authority mutation and v10 offline diagnostics in authority-specific adapters. | Prevents duplicate migration semantics without weakening existing strict authority policy. | Repo evidence gives a clear boundary; no product behavior remains open. | confirmed |
| DAQ-6 | Transfer evidence ownership and queue consumption | FR-4, DAQ-1 | 6 | recorded recommendation | Define transfer verification records with bundle/export models and pass serialized evidence through queue launch contracts; queue does not parse archives or own transfer handlers. | Closes the v11 handoff while avoiding queue-to-bundle coupling. | Existing `LaunchContract` plain-data fields provide the needed seam. | confirmed |
| DAQ-7 | Resumable migration readiness contract | FR-6, DAQ-4, DAQ-5 | 7 | recorded recommendation | Add explicit readiness/result records with blocker codes while keeping live migrated resume disabled and fail-closed. | Future resume work needs stable facts without unsafe reuse now. | User confirmed metadata/hooks only; repo evidence supports fail-closed behavior. | confirmed |
| DAQ-8 | Exporter/importer protocol breadth | FR-5 | 8 | recorded recommendation | Minimal explicit protocols and result records only; no plugin loading, automatic dispatch, or external service semantics in v12. | Prevents premature public API lock-in before stage 14 plugins and later adapters. | User confirmed no external implementations and roadmap defers dispatch. | confirmed |
| DAQ-9 | CLI command placement and current v11 surface | FR-1, FR-2, FR-3 | 9 | recorded recommendation | Add thin bundle commands under the existing runs command surface by default, and make implementation-plan drafting verify the exact command names against the current `loom runs` and `loom queue` surfaces. | CLI names are public, and v11 Phase 9 has now landed with queue operational commands. | The refreshed source evidence gives a clear default; no new user decision is needed unless the implementation plan wants a top-level command family. | confirmed |
| DAQ-10 | Bundle/offline/provider unification boundary | FRQ-1, FR-1, FR-3, FR-5 | 10 | recorded recommendation | Unify import/export around adapter-neutral portable-run exchange records and protocols. Keep local bundles and v10 offline evidence as separate first-party adapters over those records. Reserve abstract provider/transport interfaces only where v12 can define stable result and diagnostic contracts; unimplemented adapters fail explicitly. | This gives future providers a base protocol without forcing them into local archive semantics, and it keeps v10 offline authority behavior safe. | User asked whether bundle/offline run should unify and whether bundle import/export should become the base protocol; this records the safer abstraction boundary. | confirmed with protocol revision |

## Design Decisions

| ID | Decision | Selected approach | User feedback | Alternatives rejected | Rationale | Maintainability impact | Extensibility, flexibility, and expansion impact | Validation/documentation obligation | Debt and revisit trigger | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DAQ-1 | Bundle module ownership and public import path | `loom.runs` owns public bundle APIs, models, and facade methods; stores provide read models; CLI wraps public APIs. | No additional feedback needed after behavior confirmation. | Put bundle code in stores; make CLI own export/import logic; create an unrelated top-level package. | Matches `docs/structure.md` and `run-catalog.md`, keeps catalog sidecars derived, and avoids lower-layer dependency cycles. | Centralizes user-facing run collection behavior and keeps lower layers focused. | Future plugins can target public run exporter/importer protocols without moving archive ownership. | Package/import-boundary tests must prove lower layers do not import `loom.runs` bundle internals and CLI remains thin. | `loom.runs` grows broader than list/diff; revisit if bundle behavior becomes a separate service or remote catalog. | confirmed |
| DAQ-2 | Bundle manifest schema and compatibility policy | Versioned plain JSON manifest with strict format/version checks, explicit entries, checksums, payload-selection metadata, warnings, source identity, target-independent source facts, and explicit extension fields for opaque external refs. | No additional feedback needed. | Ad hoc tar layout without manifest; permissive unknown top-level fields; backend-specific remote refs in v12; binary/protobuf manifest. | Plain data matches existing serialization style and remains inspectable without project code. | Strict format boundaries reduce compatibility ambiguity. | Explicit extension fields allow stage 15 external refs without pretending v12 can validate backends. | Unit tests for version handling, manifest round-trip, unknown unsupported schema diagnostics, and opaque extension preservation. | First version may be conservative about schema evolution; revisit when stage 15 external artifact refs land. | confirmed |
| DAQ-3 | Archive, path-safety, and payload-selection boundary | Standard-library local archive helpers, metadata-only default, explicit artifact/log flags, normalized relative member paths, no symlink-follow surprises, temporary staging on import, collision rejection before commit, size reporting, and checksum verification when requested. | User confirmed conservative defaults. | Add new compression dependency; include all payloads by default; inspect by extraction; allow best-effort unsafe members. | Keeps default behavior local, dependency-light, and safe for shared bundles. | Isolates archive safety in small helpers instead of scattering path checks across CLI/API layers. | Later materialization can add remote downloads behind explicit policy without changing manifest basics. | Safety tests for traversal, symlink, missing payload, checksum mismatch, large payload warning/error, active run changed, inspect without extraction, and temporary import staging. | No signed/encrypted/deduplicated bundles; revisit when those roadmap items are selected. | confirmed |
| DAQ-4 | Import identity and collision policy | Imported copies use target-local identity; source `run_uri`, workspace/store facts, manifest identity, and evidence identity are import provenance; collisions reject by default. | User agreed to target-local identity and source-provenance preservation. | Preserve source `run_uri` as active target identity; overwrite or merge collisions; make imported runs live-resumable. | Separates portable audit facts from target-local executable identity. | Prevents confusing local path identity with target authority state. | Future migration can add explicit mapping/rebasing without changing v12 provenance. | Import tests for target identity allocation/use, source provenance, collision rejection, and catalog refresh/stale marking. | No merge/fork import policy in v12; revisit when cross-workspace sync or live migration is designed. | confirmed |
| DAQ-5 | Offline import adapter boundary | Neutral importer/result/readiness models can be shared, but `loom.authority.offline_import` keeps authority validation, collision rejection, repository mutation, replay events, and legacy diagnostics. Offline evidence is an adapter over portable-run exchange semantics, not a bundle archive. | No additional feedback needed. | Move authority mutation into `loom.runs`; replace v10 offline APIs wholesale; maintain two unrelated result models forever; force offline evidence to serialize as a local bundle before authority import. | Aligns migration concepts while preserving strict v10 public behavior and avoiding a bundle-shaped abstraction leak. | Reduces duplicate import concepts without creating authority/catalog coupling. | Later authority-backed bundle import and provider adapters can reuse the same adapter seam. | Regression tests for existing offline import diagnostics, replay events, provenance, and strict collision behavior after any refactor. | Compatibility shims may remain during v12; revisit once shared importer results fully cover authority diagnostics. | confirmed with protocol revision |
| DAQ-6 | Transfer evidence ownership and queue consumption | Transfer verification value models live with bundle/export APIs and serialize to plain data; queue launch contracts store/forward evidence mappings without archive parsing or transfer-handler ownership. | No additional feedback needed. | Make queue own bundle schemas; make bundle export depend on queue; hide evidence as human-only text. | Existing queue contracts already expose `delegated_verification` mappings and v11 deferred workspace equivalence to v12. | Keeps queue scheduling independent from transfer/archive policy. | Future transfer handlers can fill the same evidence records without queue schema churn. | Contract tests for `proven`, `unproven`, and `unsupported` evidence shape and queue-consumable serialization. | No concrete transport handlers in v12; revisit when SSH/object-store/workspace staging support lands. | confirmed |
| DAQ-7 | Resumable migration readiness contract | Add readiness result records with status and blocker codes; imported runs remain historical/non-resumable for executable behavior, and runner/planner surfaces fail closed if asked to resume them. | User confirmed readiness metadata/hooks only. | Boolean `resumable` flag; attempt best-effort reuse; omit readiness until future live migration. | Records future-useful facts without weakening v10 and v12 safety. | Makes the deferred live-resume boundary explicit and testable. | Future equivalence, rebasing, and authority-continuation work can consume the readiness record. | Model tests for blockers, import-result serialization, and diagnostics showing migrated live resume remains unsupported. | Readiness records ship before live behavior; revisit when target-store equivalence and artifact rebasing are designed. | confirmed |
| DAQ-8 | Exporter/importer protocol breadth | Minimal explicit `RunExporter`/`RunImporter` protocols over completed metadata, portable-run exchange records, manifests, selected refs, accepted evidence, and result records; no plugin loading, automatic dispatch, or external service semantics. | User confirmed no external implementations. | Build MLflow/DVC/W&B/static exporters now; auto-run exporters after completion; make protocols interpret metrics; make the local bundle archive the only protocol shape. | Keeps core domain-neutral and avoids adapter-specific lock-in before plugin discovery. | Small adapter-neutral protocols are easier to review and preserve optional dependency boundaries. | Stage 14 plugin discovery and later adapters can load implementations around these protocols without changing bundle archive internals. | Contract tests with fake exporter/importer, unsupported adapters, and package tests proving no import-time plugin discovery or optional client imports. | Protocol may need widening after real adapters; revisit during plugin or external adapter stages. | confirmed with protocol revision |
| DAQ-9 | CLI command placement and current v11 surface | Use thin CLI wrappers in the existing runs command surface by default, with exact command names selected during implementation-plan drafting against the current `loom runs` and `loom queue` command surfaces. | User accepted continuing planning with a v11 refresh dependency; design-safety review refreshed that dependency after V11 Phase 9 merged. | Freeze exact CLI names before implementation-plan review; duplicate business logic in CLI; make bundle commands top-level without checking current CLI organization. | Preserves current `loom runs` grouping, recognizes that `loom queue preflight/start/status/cancel/drain-foreground` now exists, and avoids introducing a conflicting public command family. | Keeps CLI public surface changes reviewable in the implementation plan. | Later command aliases can be added without changing Python APIs. | Implementation-plan draft must record final command names, explain any top-level command choice, and add text/JSON command tests. | CLI naming remains an implementation-plan obligation; revisit if current CLI organization makes `loom runs export/inspect/import` awkward or if a top-level bundle group is explicitly selected. | confirmed |
| DAQ-10 | Bundle/offline/provider unification boundary | Use a base portable-run exchange contract; implement local bundle archive and offline evidence as separate first-party adapters. Provider, transfer, signing, encryption, dedupe, and remote materialization hooks remain abstract or unsupported in v12 unless the implementation plan can define stable result/diagnostic contracts. | User asked to carefully consider this revision. | Collapse offline evidence into bundle format; make bundle archives the base provider protocol; implement speculative provider surfaces without diagnostics. | Keeps common import/export behavior reusable while preserving storage-specific safety and future provider flexibility. | Clarifies where abstractions belong and reduces future refactor risk. | Future provider adapters can implement `RunExporter`/`RunImporter`; deferred capabilities can attach to stable result records later. | Contract tests for local bundle, offline evidence, fake provider, and unsupported provider behavior; docs explaining bundle versus portable-run exchange. | Abstract hooks may still be too narrow; revisit during stage 14 plugins, stage 15/16 artifact interfaces, or real provider implementation. | confirmed with protocol revision |

## Design Agreement Triage

| Decision ID | Final classification | Reviewer challenge considered | Traceability | Manager action | Status |
| --- | --- | --- | --- | --- | --- |
| DAQ-1 | recorded recommendation | Could `loom.runs` become too broad? Upheld because run-catalog docs already own export/import and lower layers must stay catalog-free. | FR-1, FR-2, FR-3 | record recommendation | confirmed |
| DAQ-2 | recorded recommendation | Could strict schema block forward compatibility? Upheld because explicit extension fields preserve future data without accepting unknown top-level contracts. | FR-1, FR-2, FR-3, FR-6 | record recommendation | confirmed |
| DAQ-3 | recorded recommendation | Could archive safety be over-specified for planning? Upheld because it defines failure semantics and validation obligations, not implementation recipe detail. | FR-1, FR-2, FR-3 | record recommendation | confirmed |
| DAQ-4 | recorded recommendation | Could target-local identity complicate audit? Upheld because source identity remains provenance and active identity stays target-local. | FR-3 | record recommendation | confirmed |
| DAQ-5 | recorded recommendation | Could sharing importer models break authority compatibility? Upheld with adapter boundary and regression obligation. | FRQ-1, FR-3 | record recommendation | confirmed |
| DAQ-6 | recorded recommendation | Could queue need typed models? Upheld because plain-data evidence avoids queue/archive coupling while still allowing tests. | FR-4 | record recommendation | confirmed |
| DAQ-7 | recorded recommendation | Could readiness hooks invite unsafe resume? Upheld because live resume remains disabled and blockers are explicit. | FR-6 | record recommendation | confirmed |
| DAQ-8 | recorded recommendation | Could minimal protocols be too narrow? Upheld because real adapters and plugin loading are later roadmap stages. | FR-5 | record recommendation | confirmed |
| DAQ-9 | recorded recommendation | Could deferring exact CLI names leave behavior unclear? Refined because V11 Phase 9 is now merged; exact names remain an implementation-plan obligation against the current `loom runs`/`loom queue` surface, not an open roadmap-stage decision. | FR-1, FR-2, FR-3 | record recommendation with refreshed current-context action | confirmed |
| DAQ-10 | recorded recommendation | Could unifying around bundle archives constrain offline evidence and future providers? Upheld by making portable-run exchange the base protocol and local bundles/offline evidence separate adapters. | FRQ-1, FR-1, FR-3, FR-5 | record protocol-revision recommendation | confirmed with protocol revision |

## Design Safety Review

| Finding | Affected decision or requirement | Refactor or compatibility risk | Recommended action | Status |
| --- | --- | --- | --- | --- |
| Shared importer/result models could accidentally force `loom.authority.offline_import` to import bundle archive helpers, `RunCatalog`, or other `loom.runs` runtime behavior. | DAQ-1, DAQ-5, FR-3, FR-5 | A direct authority-to-bundle dependency would make future authority imports harder to keep compatible and could violate import-light package boundaries. | Keep neutral importer/result/readiness records plain-data and import-light. If placing them under `loom.runs` creates an import cycle or pulls archive/catalog behavior into authority, split the neutral records into an adjacent import-light module while leaving archive operations owned by `loom.runs`. Add package/import-boundary tests for `loom.runs`, `loom.authority.offline_import`, and `loom.pipeline.stores`. | recorded recommendation |
| Queue transfer evidence must remain plain data, not a queue dependency on bundle archive models. | DAQ-6, FR-4 | If queue adapters import or validate archive internals, queue scheduling becomes coupled to bundle format evolution and later transfer handlers. | Keep `LaunchContract.delegated_verification` as the queue handoff seam. The bundle/export layer may produce evidence records, but queue control modules should store, forward, and display serialized mappings only. Add contract tests for `proven`, `unproven`, and `unsupported` evidence and package tests that queue control imports do not pull bundle internals. | recorded recommendation |
| V11 Phase 9 is no longer pending, so the earlier DAQ-9 refresh dependency is stale as written. | DAQ-9, FR-1, FR-2, FR-3 | Treating Phase 9 as pending during implementation-plan drafting could produce vague CLI obligations or miss the now-current `loom queue` command family. | Overturn only the stale pending-v11 part: implementation-plan drafting should now verify final bundle command names against the current `loom runs` group and the landed `loom queue preflight/start/status/cancel/drain-foreground` surface. Use `loom runs export/inspect/import` as the default unless the implementation plan records a reason for a top-level command family. | confirmed with refinement |
| Archive safety is a public compatibility and data-loss boundary, not an implementation detail. | DAQ-2, DAQ-3, FR-1, FR-2, FR-3 | A permissive tar layout or extraction shortcut would make unsafe bundles hard to reject later and could turn inspect/import into a path traversal or symlink risk. | Keep strict manifest/version handling, normalized member paths, collision-safe temporary staging, no project-code execution, and no inspect extraction. Implementation planning must name safety tests for traversal, symlink entries, duplicate/colliding members, missing payloads, checksum mismatch, large payload diagnostics, and active-run-changed warnings. | confirmed |
| Manifest extension fields are the correct future-roadmap boundary only if v12 treats external and remote refs as opaque metadata. | DAQ-2, DAQ-8, stage 15/16 compatibility | Accepting backend-specific semantics in v12 would constrain the stage 15 external artifact contract and stage 16 materialization policy. | Preserve remote/external refs as opaque, redacted metadata only; do not validate credentials, download payloads, infer backend capabilities, or ship external exporters/importers in v12. Revisit when stage 15/16 defines backend capability and materialization contracts. | confirmed |
| Resume-readiness records are useful, but any executable migrated-resume path would invalidate v10 import safety. | DAQ-4, DAQ-5, DAQ-7, FR-6 | A boolean or best-effort resume path could accidentally treat historical imported facts as target-authoritative live state. | Keep readiness as status plus blocker codes. Imported runs remain historical/non-resumable for executable behavior; planner/runner/preflight surfaces must fail closed for migrated live resume until target-authority equivalence, artifact-ref rebasing, and authority-continuation policy are designed. | confirmed |
| `RunExporter`/`RunImporter` protocols are acceptable only as explicit callable hooks, not plugin or event-sink dispatch. | DAQ-8, FR-5, stage 14 compatibility | A broad protocol or automatic dispatch surface would lock in service-specific behavior before plugin discovery and real adapters exist. | Keep protocols minimal, domain-neutral, and free of metric semantics. Validate with fake adapters and no import-time plugin discovery or optional client imports. Revisit during stage 14 plugin discovery or a concrete external adapter plan. | confirmed |
| Bundle archives are a concrete adapter, not the base provider protocol. | DAQ-10, FRQ-1, FR-1, FR-3, FR-5 | If local bundle manifests become the base protocol, offline evidence and future providers inherit archive-specific assumptions that will be hard to unwind. | Define adapter-neutral portable-run exchange records as the base. Implement the local bundle archive and v10 offline evidence as first-party adapters. Future providers implement `RunExporter`/`RunImporter`; deferred provider/transport/signing/encryption/dedupe/materialization hooks remain unsupported unless v12 defines stable diagnostics. | confirmed with protocol revision |

Design-safety classification:

| Decision | Classification after review | Result |
| --- | --- | --- |
| DAQ-1 | recorded recommendation | Upheld with import-light model placement obligation. |
| DAQ-2 | recorded recommendation | Upheld with strict top-level schema and opaque extension-field boundary. |
| DAQ-3 | recorded recommendation | Upheld with explicit archive/path safety validation obligations. |
| DAQ-4 | recorded recommendation | Upheld; target-local identity and source provenance remain required. |
| DAQ-5 | recorded recommendation | Upheld; authority mutation and v10 diagnostics stay authority-owned. |
| DAQ-6 | recorded recommendation | Upheld; queue consumes plain serialized evidence only. |
| DAQ-7 | recorded recommendation | Upheld; readiness records do not enable live migrated resume. |
| DAQ-8 | recorded recommendation | Upheld; protocols stay explicit, minimal, and adapter-ready. |
| DAQ-9 | recorded recommendation with refinement | Stale pending-v11 dependency overturned; current v11 Phase 9 CLI/preflight surface must guide exact command naming. |
| DAQ-10 | recorded recommendation with protocol revision | Upheld; portable-run exchange is the base protocol, while local bundles and offline evidence stay separate adapters. |

Gate result:

- Status: passed
- Reviewer: bounded roadmap-stage design-safety review on 2026-05-14
- Blockers: none
- Decisions needing discussion: none
- Recorded recommendations: DAQ-1 through DAQ-10 are recorded recommendations
- Accepted risks: exact CLI command names remain an implementation-plan choice
  against the current CLI surface; portable-run exchange records and
  importer/exporter protocols may need widening when real adapters arrive;
  transfer handlers and deferred provider capabilities remain unsupported in
  v12; neutral shared import models may need careful placement to avoid
  authority/catalog coupling.
- Revisit triggers: stage 14 plugin discovery, stage 15/16 external artifact
  and materialization work, concrete cross-workspace transfer demand, or a
  later live migrated-resume design.

## Practical Design Notes

Public Python API surface:

- Public portable-run exchange and bundle/export/import models and operations
  live under `loom.runs`, or in an adjacent import-light module if
  implementation-plan review finds that authority/offline import would
  otherwise import archive behavior.
- `RunCatalog` may expose convenience methods for local run-collection export,
  inspect, and import while public free functions remain acceptable if the
  implementation plan finds that clearer.
- Minimal `RunExporter` and `RunImporter` protocols are explicit callable
  interfaces. They are not plugin discovery, automatic post-run dispatch, or
  external service adapters in v12.
- Shared importer/exporter result models should be plain-data serializable and
  usable by local bundle workflows, v10 authority offline-import adapters, fake
  contract adapters, and future provider adapters.
- Shared neutral records must remain import-light. Authority/offline-import
  code may depend on neutral result/readiness records, but it must not import
  archive helpers, `RunCatalog` facade methods, CLI modules, queue controllers,
  plugin discovery, or optional external clients.
- Local bundle manifests are one adapter's durable storage format; they are not
  the base provider protocol.

CLI surface:

- CLI remains a thin caller of public Python APIs.
- Bundle commands should use the existing runs command surface by default, with
  exact command names selected during implementation-plan drafting against the
  current landed CLI surface: `loom runs index/list/diff` and
  `loom queue preflight/start/status/cancel/drain-foreground`.
- CLI output must support text and JSON result envelopes and should map
  unsupported transfer, unsafe bundle, collision, and resume-blocked cases to
  structured diagnostics.

Persisted records and file layout:

- Bundle archives contain a versioned plain JSON manifest, entry records,
  checksums, payload-selection metadata, source run/workspace facts, warnings,
  import/export compatibility facts, and explicit extension fields for opaque
  external refs.
- Imported runs use target-local identity and preserve source identity only in
  provenance/import metadata.
- Catalog state remains derived. Import may refresh or mark the catalog stale,
  but the catalog sidecar does not become authoritative.

Import boundaries and dependencies:

- `loom.runs` should not bypass authority-backed completed-run read models when
  authoritative facts are available.
- `loom.cli` should remain a thin caller of public APIs.
- Core bundle behavior should not require external service, cloud, compression,
  exporter, plugin, or domain dependencies.
- Queue control modules should not import bundle archive internals. Transfer
  evidence crosses into queue as plain structured mappings suitable for
  `LaunchContract.delegated_verification` and dispatch evidence.
- Package/import-boundary tests should cover `loom.runs` cheap imports,
  `loom.pipeline.stores` not importing `loom.runs`, queue control modules not
  importing bundle internals, and authority offline import not importing
  archive/catalog behavior when it only needs neutral result models.

Failure modes and diagnostics:

- Confirmed baseline includes unsupported transfer kind, import collision,
  invalid or incomplete offline evidence, unsafe bundle path, checksum
  mismatch, non-terminal import source, active run changed during read,
  unexpected large payload, stale catalog state, unsupported archive format, and
  live-resume blocked for migrated imports.

Extension points and flexibility boundaries:

- Manifest extensions may preserve opaque external refs but cannot claim remote
  backend validation or payload materialization before the stage 15/16 work.
- Transfer verification records are the extension point for later concrete
  transport handlers. V12 records unsupported operations explicitly.
- Importer/exporter protocols leave room for stage 14 plugin loading without
  loading plugins or optional clients at import time.
- Migration-readiness records are future-facing facts; runner/planner live
  reuse remains disabled for imported historical runs.

Maintainability assessment:

- The design keeps user-facing bundle behavior in one public area,
  `loom.runs`, and leaves lower layers to provide authoritative metadata and
  local path helpers. This reduces scattered archive/import logic and protects
  lower-layer import boundaries.
- The main maintainability risk is `loom.runs` becoming a catch-all for every
  future export concern. The explicit protocol, adapter, and stage 14 plugin
  boundaries are the mitigation.

Extensibility assessment:

- Versioned manifests, explicit extension fields, transfer evidence models, and
  readiness blocker codes provide expansion points without committing v12 to
  remote backends, concrete external exporters, or live migrated resume.
- Future real adapters may require widening `RunExporter`/`RunImporter`, so
  fake adapter contract tests should keep the protocol minimal but not
  under-specified.

Flexibility and expansion assessment:

- Local archive/import comes first, but the manifest can preserve non-local refs
  as metadata and transfer records can later be produced by SSH/object-store or
  workspace-staging handlers.
- Target-local identity plus source provenance leaves room for future
  run-identity mapping and artifact-ref rebasing without retrofitting v12
  imported runs.

Scalability and future compatibility:

- Metadata-only default export avoids accidentally copying large payloads.
- Explicit payload selection and size reporting make large-run behavior visible
  without adding deduplication or remote materialization now.
- Strict manifest version handling plus extension fields should keep future
  bundle evolution reviewable.

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
| Metadata-only completed-run export | Conservative archive behavior and manifest creation | Synthetic terminal run with authoritative metadata | Unit/integration export tests; CLI/API docs | confirmed |
| Bundle inspection without extraction | Safe review and summary output | Bundle fixture with manifest and payload-selection metadata | Inspect tests and CLI JSON/text output coverage | confirmed |
| Safe import into temporary collection | Manifest validation, safe path handling, catalog stale marking | Temporary local run collection | Import tests with collision and unsafe path cases | confirmed |
| Offline evidence import through shared importer | Existing v10 evidence imports use the same importer/result semantics as bundle import | Offline evidence fixture from current tests | Regression tests around strict rejection, replay events, and provenance | confirmed |
| Resumable migration readiness report | Import result explains why migrated live resume is blocked or potentially candidate-only | Bundle/offline evidence import fixture | Model and diagnostic tests; docs showing deferral boundary | confirmed |
| Delegated transfer evidence | Proven/unproven workspace checks for queue launch contracts | Queue launch contract or preflight fixture | Serialization/contract test for evidence shape | confirmed |
| Fake compatibility exporter/importer | `RunExporter` and `RunImporter` result models without external tools | Fake exporter over portable-run exchange records and manifest refs; fake importer over bundle/offline evidence records | Contract test | confirmed with protocol revision |
| Unsupported provider adapter | Deferred provider/transport hooks fail explicitly instead of silently falling back | Fake provider or transfer kind that is not implemented in v12 | Contract/unit diagnostics test | confirmed with protocol revision |

## Validation Strategy

| Area | Behavior validated | Required coverage | Test/check type | Command or location | Status |
| --- | --- | --- | --- | --- | --- |
| Package/import boundaries | Bundle APIs are import-light and do not import CLI, queue controllers, plugins, external tools, or project code at import time; stores do not import bundle internals; queue control modules consume transfer evidence as plain mappings; authority offline import can use neutral result models without importing archive/catalog behavior. | Package tests | Package | `tests/package` | confirmed |
| Manifest models | Schema versioning, entry validation, checksum fields, payload selection metadata. | Unit tests | Unit | `tests/unit/loom/runs` or equivalent | confirmed |
| Export | Completed-run metadata projection, metadata-only default, optional artifact/log payload inclusion, size/path reporting. | Unit and integration tests | Unit/integration | `tests/unit`, `tests/integration` | confirmed |
| Safety | Path traversal, symlink, partially written run, missing payload, checksum mismatch, and large unexpected payload handling. | Focused unit/integration tests | Unit/integration | `tests/unit`, `tests/integration` | confirmed |
| Inspect | Manifest read and summary without extraction. | Unit/CLI tests | Unit/contract/integration | `tests/contracts`, `tests/integration` | confirmed |
| Import | Safe extraction into temporary collection, collision rejection, checksum verification, catalog stale marking or refresh. | Integration tests | Integration | `tests/integration` | confirmed |
| Offline import alignment | Existing offline evidence import validation, rejection diagnostics, replay events, and historical provenance survive through shared importer alignment. | Unit/integration regression tests | Unit/integration | `tests/unit/loom/authority`, `tests/integration/authority` | confirmed |
| Resumable migration readiness | Importer result carries eligibility/blocker facts, and runner/planner surfaces still reject migrated live resume. | Unit/contract tests | Unit/contract | `tests/unit`, `tests/contracts` | confirmed |
| Transfer evidence | Queue-consumable verification record shape and status semantics. | Contract tests | Contract | `tests/contracts` | confirmed |
| Exporter/importer protocols | Local bundle, offline-evidence, fake, and unsupported adapters return structured result records over portable-run exchange records, completed metadata, bundle refs, and offline evidence refs. | Contract tests | Contract | `tests/contracts` | confirmed with protocol revision |
| CLI | Thin text/JSON wrappers for export, inspect, import. | CLI integration tests | Integration/e2e | `tests/integration` and limited `tests/e2e` | confirmed |
| PR gate | Full repository validation before PR preparation. | Required checks | Make targets | `make validate-pr`; `make test-summary` | confirmed |

## Phase Sketch

Confirmed phase sketch after examples and validation strategy review.

### Phase 1 - Portable Exchange And Bundle Manifest Contracts

Goal:

- Establish the adapter-neutral portable-run exchange records plus the local
  bundle manifest, import/export result, transfer evidence, and readiness value
  models without archive I/O or CLI behavior.

Scope:

- Versioned plain-data manifest and entry models.
- Portable-run source identity, target identity policy, selected entries,
  payload refs, adapter identity, diagnostics, import/export result, and
  extension-field records.
- Payload selection and checksum metadata models.
- Import/export/inspection result envelopes and diagnostics.
- `RunBundleExportOptions`, `RunBundleExportResult`, `RunBundleInspection`,
  `RunBundleImportPolicy`, `RunBundleImportResult`, and
  `MigrationResumeReadiness` public records.
- Neutral record placement and import-light boundaries for bundle,
  transfer-evidence, authority-import, and queue consumers.
- Package/import-boundary guardrails for `loom.runs`, authority, queue, stores,
  and CLI.

Out of scope:

- Archive write/read implementation.
- Local collection import/extraction.
- CLI commands.
- Real exporters/importers and transfer handlers.
- Provider-specific adapters beyond local bundle, offline-evidence, fake, and
  unsupported contract fixtures.

Acceptance criteria:

- Public models round-trip through plain data.
- Unsupported schema/version diagnostics are structured.
- Strict version and unknown top-level manifest behavior is explicit.
- Extension fields preserve opaque external refs without interpreting them.
- Local bundle manifests and v10 offline evidence can both map to shared
  portable-run exchange records without either becoming the other's storage
  format.
- Deferred provider hooks expose structured unsupported diagnostics or
  `NotImplementedError` behavior.
- Import-boundary tests prove neutral records do not pull archive/catalog
  behavior into authority or queue modules.

Test expectations:

- Package: import-boundary coverage for `loom.runs`, authority/offline import,
  queue, stores, CLI, plugins, and optional dependencies.
- Unit: manifest/result/readiness model validation and serialization.
- Contract: plain-data public-record compatibility for local bundle,
  offline-evidence, fake, and unsupported adapters.
- Integration: not required beyond import smoke.
- E2E: not required.
- Opt-in: none.

Design impact:

- Public API, base provider protocol, and persisted manifest compatibility
  start here.

Future compatibility:

- Extension fields preserve opaque external refs for stage 15/16 without
  backend semantics.
- Public record placement leaves room for stage 14 plugin adapters without
  requiring plugin discovery in v12.
- Future providers implement adapter protocols over portable-run exchange
  records rather than inheriting local bundle archive semantics.

Alternatives rejected:

- CLI-owned models, store-owned bundle archives, permissive top-level manifest
  schemas, ad hoc tar layouts without manifests, binary manifests, and
  service-specific exporter contracts. Also reject making bundle archives the
  base provider protocol or forcing offline evidence to become a bundle before
  import.

Debt introduced:

- Schema starts conservative; revisit when external artifact/exporter contracts
  need concrete additional fields.
- Abstract provider hooks may need widening when real providers are designed.

Reviewability:

- Small model/API phase with package and unit evidence.

### Phase 2 - Export, Archive Safety, And Inspect

Goal:

- Implement safe metadata-only export, explicit payload/log inclusion, archive
  member safety, checksum/size reporting, and inspect without extraction.

Scope:

- Portable-run export record assembly from completed-run metadata and selected
  materialized refs.
- Local bundle manifest materialization from portable-run export records.
- Standard-library local archive write/read helpers.
- Path traversal, symlink, duplicate/colliding member, missing payload, checksum,
  large payload, and active-run-changed diagnostics.
- Bundle inspection API that reads manifests and optional checksum evidence
  without extraction.

Out of scope:

- Import into run collections.
- Offline evidence alignment.
- CLI commands except internal formatting helpers if needed by tests.
- Remote payload downloads or external ref validation.

Acceptance criteria:

- A synthetic completed run can be exported as metadata-only by default.
- Export first produces shared exchange records, then the local bundle adapter
  materializes the archive/manifest.
- Explicit payload/log flags broaden export intentionally.
- Inspect reports summaries without extracting to the current directory.
- Unsafe archive members and changing run reads fail or warn with structured
  diagnostics.

Test expectations:

- Package: maintain Phase 1 boundaries.
- Unit: archive path normalization, manifest builder, payload selection.
- Contract: inspect result shape where useful.
- Integration: export/inspect over temporary completed runs and bundle fixtures.
- E2E: not required.
- Opt-in: none.

Design impact:

- Defines the archive safety behavior that later import and CLI phases rely on.

Future compatibility:

- Remote refs remain metadata-only; explicit materialization waits for later
  roadmap stages.

Alternatives rejected:

- Include all payloads by default, add compression dependencies, inspect by
  extraction, or allow best-effort unsafe members.

Debt introduced:

- No signed, encrypted, deduplicated, or cross-machine synchronized bundles.

Reviewability:

- Focused implementation around export/inspect plus safety tests.

### Phase 3 - Import, Offline Alignment, And Resume Readiness

Goal:

- Implement safe bundle/offline-evidence import through shared portable-run
  import records with target-local identity, source provenance, collision
  rejection, offline-import compatibility, and resume-readiness blocker
  reporting.

Scope:

- Import policy/result models in use.
- Local bundle import adapter and v10 offline-evidence import adapter both map
  into portable-run import records.
- Target-local identity resolution and source provenance records.
- Temporary staging and safe commit behavior for local run collections.
- Catalog refresh or stale marking after import.
- Shared neutral importer/result model alignment with
  `loom.authority.offline_import` while preserving v10 diagnostics, replay
  events, repository mutation boundaries, and historical-only provenance.
- Resume-readiness records and fail-closed live-resume diagnostics.

Out of scope:

- Live migrated resume.
- Merge/fork/overwrite import policies.
- Authority mutation outside explicit authority import adapters.
- Cross-workspace synchronization.

Acceptance criteria:

- Bundle import rejects unsafe paths and collisions before commit.
- Offline evidence import preserves v10 behavior while using shared result
  semantics; it is not forced through the local bundle archive format.
- Imported copies use target-local identity and record source identity.
- Existing offline import behavior remains compatible.
- Resume-readiness blockers are reported, and live migrated resume remains
  unsupported.

Test expectations:

- Package: authority does not import archive helpers or `RunCatalog` behavior.
- Unit: import policy/result/readiness diagnostics.
- Contract: importer result shape, adapter identity, unsupported-adapter
  diagnostics, and blocker codes.
- Integration: local temporary collection import, collision rejection, offline
  evidence regression tests, catalog refresh/stale behavior.
- E2E: not required.
- Opt-in: none.

Design impact:

- Locks the migration/import boundary and source-versus-target identity model.

Future compatibility:

- Future live migration can consume readiness facts after target-authority
  equivalence and artifact rebasing are designed.

Alternatives rejected:

- Preserve source `run_uri` as active identity, overwrite collisions, or attempt
  best-effort migrated live resume.
- Force offline evidence to serialize as a bundle before import.

Debt introduced:

- Compatibility shims may remain until neutral importer results fully cover
  authority diagnostics.

Reviewability:

- Split after export/inspect so import safety and offline compatibility can be
  reviewed separately.

### Phase 4 - Transfer Evidence And Importer/Exporter Protocols

Goal:

- Add queue-consumable transfer verification records and minimal explicit
  importer/exporter protocol behavior over portable-run exchange records
  without concrete transfer handlers or external providers.

Scope:

- `proven`, `unproven`, and `unsupported` transfer verification records.
- Plain-data serialization for queue launch-contract and delegated-verification
  consumption.
- Minimal explicit `RunExporter`/`RunImporter` protocol call paths and fake
  adapter contract coverage.
- Unsupported provider, exporter/importer, and transfer adapter contracts for
  deferred capabilities.
- Unsupported transfer diagnostics for Python and CLI/structured consumers.

Out of scope:

- SSH, object-store, remote workspace, or automatic staging handlers.
- Plugin discovery or automatic exporter dispatch.
- MLflow, DVC, W&B, static report, or service-specific adapters.

Acceptance criteria:

- Queue/delegated-launch surfaces can reference transfer evidence without
  parsing bundle archives.
- Fake importer/exporter contracts demonstrate the minimal protocol.
- Unsupported transfer/provider handlers fail explicitly.

Test expectations:

- Package: queue control modules do not import bundle archive internals.
- Unit: transfer evidence model validation and unsupported diagnostics.
- Contract: queue-consumable evidence shape plus fake and unsupported
  importer/exporter contracts.
- Integration: narrow queue/preflight evidence formatting where needed.
- E2E: not required.
- Opt-in: none.

Design impact:

- Creates the v11 handoff evidence model while preserving queue scheduling
  independence.

Future compatibility:

- Future concrete handlers can populate the same evidence records.
- Future provider adapters can implement the same protocols without depending
  on local bundle archive internals.

Alternatives rejected:

- Queue-owned bundle schemas, archive parsing in queue adapters, hidden
  human-only evidence, automatic exporter dispatch, and speculative provider
  adapters without structured unsupported behavior.

Debt introduced:

- Transfer handlers remain unsupported until a later stage selects them.
- Provider abstractions may need widening once a real adapter exists.

Reviewability:

- Contract-heavy phase with clear package-boundary and queue evidence checks.

### Phase 5 - CLI, Docs, Hardening, And Final Validation

Goal:

- Expose the confirmed bundle workflows through thin CLI commands, update docs,
  harden diagnostics, and run the final validation gate.

Scope:

- Exact CLI command names selected against current `loom runs` and `loom queue`
  surfaces, with `loom runs export/inspect/import` as the default unless the
  implementation plan records a better fit.
- Text and JSON CLI output for export, inspect, and import.
- CLI mapping for unsupported transfer, unsafe bundle, collision, checksum, and
  resume-blocked diagnostics.
- User-facing docs for defaults, safety behavior, source/target identity,
  deferrals, the portable-run exchange versus local bundle distinction, and
  protocol limits.
- Final suite evidence and PR body inputs.

Out of scope:

- New external integrations.
- Network/cluster tests.
- Automatic exporter dispatch.

Acceptance criteria:

- CLI wrappers call public Python APIs and duplicate no bundle/store logic.
- Docs explain metadata-only defaults, inspect-without-extraction, safe import,
  target-local identity, bundle/offline adapter behavior, and live-resume
  deferral.
- `make validate-pr` and `make test-summary` are run or blockers are recorded.

Test expectations:

- Package: final import-boundary sweep.
- Unit: CLI formatting helpers where useful.
- Contract: JSON schema/envelope expectations where useful.
- Integration: CLI export/inspect/import text and JSON flows.
- E2E: limited happy-path local bundle workflow if existing e2e conventions
  support it.
- Opt-in: none.

Design impact:

- Public CLI surface becomes visible here.

Future compatibility:

- Later aliases or plugin-loaded commands can wrap the same Python APIs.

Alternatives rejected:

- Business logic in CLI, top-level command family without current-surface
  justification, or external-service examples in core docs.

Debt introduced:

- CLI naming remains an implementation-plan obligation until final command
  review in this phase.

Reviewability:

- Final integration and documentation phase after core behavior is already
  tested.

## Implementation Readiness

| Check | Evidence | Result | Required action |
| --- | --- | --- | --- |
| Roadmap-to-requirement traceability | Roadmap framing, intent discovery, capability triage, functionality agreement, and behavior baseline are confirmed. | pass | None. |
| Requirement-to-design traceability | Proposed implementation shape, design-agreement queue, design decisions, and design triage are confirmed. | pass | None. |
| Design-safety review completed | Bounded review passed on 2026-05-14 with no blockers or needs-discussion decisions; DAQ-9 refreshed against the now-current V11 Phase 9 surface and DAQ-10 records the portable-run exchange adapter boundary. | pass | Carry design-safety validation obligations into examples, validation strategy, phase shaping, and the implementation-plan quality gate. |
| Example-to-validation traceability | Examples and validation strategy are confirmed, with deterministic local coverage and no remote, plugin, network, or cluster dependency. | pass | None. |
| Phase-shaping readiness | Five-phase sketch is confirmed: portable exchange/contracts, export/inspect safety, import/offline alignment/readiness, transfer evidence/protocols, and CLI/docs/hardening. | pass | None. |
| Unresolved blocked or needs-discussion functionality or design decisions | No functionality, design-agreement, or design-safety blockers or needs-discussion decisions remain. | pass | None. |

Readiness result:

- Status: ready for implementation-plan drafting
- Implementation-plan drafting blockers:
  - None after final planning confirmation on 2026-05-14.
- Accepted risks:
  - CLI command names remain an implementation-plan choice against the current
    v11 Phase 9 CLI/preflight surface.
  - `RunExporter`/`RunImporter` intentionally stay minimal before stage 14
    plugin discovery and concrete external adapters.
  - Portable-run exchange records are intentionally adapter-neutral and may
    need widening when real providers are designed.
  - Transfer evidence records exist before concrete transfer handlers, so
    unsupported operations remain explicit diagnostics in v12.
  - Shared importer/result model placement must avoid authority/catalog import
    coupling.
- Assumptions to carry forward:
  - V12 remains local, conservative, and dependency-light unless user direction
    changes during planning.

## Open Questions

| Question | Affects | Current default | Status |
| --- | --- | --- | --- |
| Do you have clarifying questions about the v12 briefing before capability triage starts? | Roadmap framing | No clarifying questions before proceeding. | closed |
| What should v12 optimize for relative to the roadmap: safe archive/import, v11 transfer evidence, external exporter compatibility, or a different priority? | Roadmap framing and intent discovery | Optimize first for safe conservative archive/import plus concrete transfer evidence; keep exporter hooks minimal. | closed |
| Should implementation-plan drafting wait for v11 Phase 9 to merge, or may it draft with an explicit Phase 9 refresh dependency? | Handoff and implementation planning | Resolved by current context: V11 Phase 9 is merged as of 2026-05-14, so implementation-plan drafting should use the current CLI/preflight surface. | closed |
| Should bundle/offline imports remain terminal historical migrations in v12, or should v12 reopen resumable live continuation semantics after import? | Functionality agreement and import behavior | Preserve v10 historical/non-resumable import semantics; record resume-readiness metadata and blockers only; treat live continuation after import as future work unless explicitly reopened. | closed |
| Should v12 provide resume-readiness metadata and hooks while keeping actual migrated live resume unsupported? | Functionality agreement and design agreement | Yes: add explicit eligibility/blocker records and extension hooks, but do not let the runner resume migrated imports in v12. | closed |
| When importing a bundle into a different workspace or run collection, should Loom preserve the source `run_uri` as identity, or allocate a target-local identity while preserving the source identity as provenance? | Functionality agreement and import behavior | Allocate or use a target-local run identity for the imported copy, reject target collisions, and preserve the source `run_uri` and bundle/evidence identity in import provenance. | closed |

## Handoff Notes

Implementation-plan draft inputs:

- Ready. The user confirmed this planning artifact on 2026-05-14 and requested
  the implementation-plan draft from it. Use these notes as the primary source
  for `docs/roadmap/stage-12/implementation-plan.md`.

Design-safety review result:

- Passed on 2026-05-14. No blocker or needs-discussion decision remains.
- DAQ-1 through DAQ-8 are upheld as recorded recommendations.
- DAQ-9 is upheld with refinement: V11 Phase 9 has merged, so exact bundle CLI
  names should be selected against the current `loom runs` and `loom queue`
  surfaces rather than carried as a pending-Phase-9 dependency.
- DAQ-10 is recorded with protocol revision: portable-run exchange records are
  the base abstraction, while local bundles and v10 offline evidence remain
  separate first-party adapters.

Validation and phase-shaping inputs:

- Confirmed. Use the examples, validation matrix, and five-phase sketch above
  as implementation-plan inputs.

Plan-quality-gate risks:

- Design must preserve the confirmed target-local import identity, collision
  rejection, and source-provenance behavior through concrete public models.
- Design must preserve the confirmed terminal/historical-only import boundary
  while exposing resume-readiness blockers without enabling live continuation.
- Potential public API overreach in `RunExporter`/`RunImporter` before plugin
  discovery and remote stores.
- Potential abstraction error if implementation makes the local bundle manifest
  the base provider protocol instead of making it a concrete adapter over
  portable-run exchange records.
- Potential import-boundary drift if neutral importer/result models make
  authority/offline import depend on bundle archive helpers or `RunCatalog`
  behavior.
- Potential queue/bundle coupling if queue adapters parse archives instead of
  consuming plain transfer evidence mappings.

Assumptions to carry forward:

- V12 should keep Loom domain-neutral.
- V12 should use standard-library archive support by default.
- V12 should not execute project code during export, inspect, or import.
- V12 should preserve authority truth versus local materialization boundaries.
- V12 should align local bundle import/export with v10 offline import through
  shared portable-run exchange records and importer/exporter contracts, while
  keeping local bundles and offline evidence as separate first-party adapters.
