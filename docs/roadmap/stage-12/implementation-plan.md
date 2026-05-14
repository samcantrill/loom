# Implementation Plan v12: Portable Run Exchange, Bundles, Transfer Evidence, And Exporters

## Metadata

- Status: Phase 3 in progress
- Roadmap stage: `v12`
- Source planning notes:
  `docs/roadmap/stage-12/planning.md`
- Workflow: `.codex/workflows/roadmap-stage-implementation.md`
- Related implementation plans:
  - `docs/roadmap/stage-11/implementation-plan.md`
  - `docs/roadmap/stage-10/implementation-plan.md`
  - `docs/roadmap/stage-8/implementation-plan.md`
  - `docs/roadmap.md`
- Related source docs:
  - `docs/structure.md`
  - `docs/features/run-catalog.md`
  - `docs/features/run-store.md`
  - `docs/features/artifacts.md`
  - `docs/features/io.md`
  - `docs/features/cli.md`
  - `docs/features/testing.md`
  - `docs/features/remote-stores.md`
  - `docs/features/plugins.md`
- Draft pass: complete on 2026-05-14 from confirmed Stage 12 planning notes
- Refine pass: complete on 2026-05-14 after local plan-quality review
- Plan quality gate: passed on 2026-05-14 after local
  review/refinement/confirmation
- Current phase: Phase 3, Import, Offline Alignment, And Resume Readiness
- Blockers:
  - No roadmap-stage planning blocker remains.
  - No plan-quality blocker remains; Phase 2 execution planning may begin.

## Summary

- Goal: define adapter-neutral portable-run exchange records, implement the
  first local bundle adapter, align v10 offline evidence as a separate
  first-party adapter, expose safe export/inspect/import workflows, and publish
  queue-consumable transfer evidence.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-12/planning.md`.
- Approved behavior: metadata-only export by default; inspect without
  extraction; target-local import identity with source provenance; strict
  collision rejection; migrated live resume disabled with readiness blockers.
- Source behavior confirmation: complete in the planning artifact.
- Key design constraints: domain-neutral, dependency-light, no project code
  execution during export/inspect/import, no queue dependency on bundle archive
  internals, no provider-specific adapters in v12.
- Source design-agreement gate: confirmed with DAQ-1 through DAQ-10.
- Future-roadmap impact: stage 14 plugin discovery, stage 15/16 external and
  remote artifact interfaces, later transfer handlers, later live migrated
  resume, and later exporter implementations must be able to build on these
  records without inheriting local bundle archive assumptions.
- Reusable interface, adapter, or protocol assumptions: portable-run exchange
  records are the base abstraction; local bundles and v10 offline evidence are
  separate first-party adapters; future providers implement explicit
  `RunExporter` and `RunImporter` protocols.
- Examples covered: metadata-only export, inspect without extraction, safe
  local import, offline-evidence import alignment, resume-readiness reporting,
  delegated transfer evidence, fake importer/exporter, and unsupported adapter
  diagnostics.
- Source phase shaping: five phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-14 after local
  review/refinement/confirmation.
- Out of scope: signed/encrypted/deduplicated bundles, external provider
  implementations, plugin discovery, automatic post-run dispatch, concrete SSH
  or object-store transfer handlers, remote payload materialization, and live
  migrated resume.

## Goal

Implement v12 as a portable-run exchange layer with one concrete local bundle
adapter and one aligned offline-evidence adapter.

When the stage is complete, users can export completed run facts and selected
payloads into a safe local bundle, inspect that bundle without extraction,
import the bundle into a local run collection or authority-backed target through
the same importer-result semantics used by offline evidence, and view transfer
verification evidence that queue and delegated-launch surfaces can cite without
parsing bundle internals.

## Context

The current repository already has the pieces v12 should build on:

- `loom.runs` exposes the public run-catalog facade and CLI-backed
  `loom runs index/list/diff` commands.
- `read_completed_run_bundle_metadata(...)` and related read models under
  `loom.pipeline.stores.materialization_read_models` expose payload-free
  completed-run facts and materialized references.
- v10 offline evidence and `loom.authority.offline_import` validate strict
  terminal offline import, reject collisions, record replay events, and mark
  imported facts as historical and non-resumable.
- `loom.queue` already records launch-contract evidence through plain
  structured mappings, and the landed v11 CLI surface includes
  `loom queue preflight/start/status/cancel/drain-foreground`.
- The CLI is argparse-based and intentionally thin: command handlers import
  public Python APIs lazily and format text or JSON envelopes.

The confirmed planning revision is the core design constraint: do not make
local bundle archives the provider protocol. The base abstraction is
adapter-neutral portable-run exchange records and importer/exporter result
semantics. Local bundles are the first concrete archive/storage adapter.
Offline evidence remains a Loom-specific authority adapter over the same result
semantics and must preserve v10 safety behavior.

## Planning Readiness

- Source planning notes:
  `docs/roadmap/stage-12/planning.md`
- Functionality and behavior baseline:
  complete; the notes lock export, inspect, import, transfer evidence,
  importer/exporter protocols, readiness metadata, and explicit unsupported
  behavior.
- Design-safety review:
  passed on 2026-05-14 with no unresolved blocker or needs-discussion decision.
  The review added two plan-critical obligations: neutral importer/result
  models must stay import-light, and bundle archives must remain one adapter,
  not the base provider protocol.
- Examples and validation strategy:
  complete; default validation is local and deterministic, with no real remote
  services, plugins, network, clusters, or external provider dependencies.
- Phase shaping:
  complete; five implementation phases are recorded below.
- Implementation readiness blockers from planning:
  none after final planning confirmation on 2026-05-14.
- Accepted risks and revisit triggers:
  CLI command names are now selected as `loom runs export`, `loom runs inspect`,
  and `loom runs import`; revisit only if implementation finds that the current
  `loom runs` grouping cannot host them cleanly. The minimal protocols may need
  widening when stage 14 plugin discovery or a real provider adapter arrives.
  Deferred transfer, provider, signing, encryption, dedupe, and remote
  materialization hooks must remain unsupported unless v12 can define stable
  result and diagnostic contracts.

## Desired Outcome

When all phases are complete:

- Public plain-data models describe portable-run source identity, target-local
  identity policy, selected records, payload refs, diagnostics, adapter
  identity, import/export results, transfer evidence, and migration-resume
  readiness.
- Local bundle manifests are versioned plain JSON with strict format/version
  handling, entry records, checksums, payload-selection metadata, warnings,
  source identity facts, and extension fields for opaque external refs.
- `RunCatalog` or public `loom.runs` functions can export completed runs,
  inspect bundle archives without extraction, and import bundle archives safely.
- Export first builds portable-run exchange records and only then materializes
  the local bundle adapter.
- Bundle import and offline-evidence import both map adapter-specific evidence
  into shared portable-run import result semantics, while authority mutation
  remains authority-owned.
- Imports use target-local identity, preserve source `run_uri`,
  workspace/store facts, and bundle/evidence identity in provenance, and reject
  collisions by default.
- Imported runs remain historical and non-resumable for executable behavior.
  Import results expose readiness status plus blocker codes for future live
  migration work.
- Transfer evidence records use `proven`, `unproven`, and `unsupported`
  statuses and serialize to plain mappings suitable for
  `LaunchContract.delegated_verification`.
- Minimal explicit `RunExporter` and `RunImporter` protocols exist with local
  bundle, offline-evidence, fake, and unsupported-adapter contract coverage.
- CLI commands `loom runs export`, `loom runs inspect`, and
  `loom runs import` expose text and JSON wrappers over public Python APIs.

## Non-Goals

- No concrete SSH, object-store, remote workspace, automatic staging, or
  network transfer handlers.
- No external provider implementations, including MLflow, DVC, W&B, static
  report writers, or hosted tracking services.
- No plugin discovery, import-time plugin loading, automatic exporter dispatch,
  or event-sink dispatch.
- No signed, encrypted, deduplicated, or synchronized bundle format.
- No domain-specific metric, model, dataset, or report semantics.
- No best-effort live resume from migrated imports.
- No authority mutation from local bundle code except through explicit
  authority import adapters.
- No queue-owned bundle archive schema or queue archive parsing.

## Constraints

- Keep `loom` domain-neutral.
- Preserve source-tree and import boundaries from `docs/structure.md`.
- Do not introduce heavyweight runtime dependencies; use standard-library
  archive support by default.
- Treat authored configs as trusted project code, but do not execute project
  code during export, inspect, or import.
- Keep CLI as an outer layer over public Python APIs.
- Keep run-store and authority facts authoritative; catalog state remains a
  derived projection.
- Keep neutral portable-run result models import-light enough for authority
  offline import to use without importing archive helpers or `RunCatalog`.
- Keep queue transfer evidence plain-data and queue-consumable.
- Preserve existing v10 offline-import diagnostics, replay events, collision
  rejection, authority mutation boundaries, and historical-only provenance.
- Run `make validate-pr` and `make test-summary` before each phase PR is
  prepared, or record why either command could not run.

## Design Principles

- **Portable exchange first.** Shared import/export behavior belongs in
  adapter-neutral records and result semantics, not in the local bundle archive
  format.
- **Concrete adapters stay honest.** Local bundles and offline evidence are
  first-party adapters with different storage and validation rules.
- **Authority truth remains authority truth.** Bundle and catalog code may
  project or import facts through explicit adapters, but must not bypass
  authority-owned mutation policy.
- **Inspect and import fail closed.** Unsafe paths, symlink surprises, checksum
  mismatch, collisions, unsupported versions, unsupported providers, and
  resume-blocked cases must be structured diagnostics.
- **Queue consumes evidence, not archives.** Transfer verification crosses into
  queue launch contracts as plain mappings only.
- **Default export is conservative.** Metadata-only export avoids unexpected
  large payload movement; payload/log inclusion is explicit.
- **Deferred capabilities need explicit seams.** Abstract hooks are acceptable
  only when their v12 result and diagnostic contracts are stable; otherwise the
  behavior is unsupported.
- **Future compatibility must not weaken present safety.** Readiness records
  can reserve facts for later live migration, but imported runs remain
  historical and non-resumable in v12.

## Key Design Choices

- Public bundle, exchange, import/export, inspection, transfer-evidence, and
  readiness APIs are owned by `loom.runs` unless the quality gate finds a
  concrete import-cycle risk. If neutral records cannot live there without
  pulling archive behavior into authority, split those records into an
  import-light adjacent module while leaving archive operations in `loom.runs`.
- Local bundle manifests are strict versioned JSON. Unknown future data is
  allowed only inside explicit extension fields, and remote/external refs are
  opaque metadata in v12.
- Archive helpers use standard-library local archive support with normalized
  relative member paths, no unsafe symlink following, duplicate/collision
  detection, size accounting, temporary staging, and checksum support.
- Minimal `RunExporter` and `RunImporter` protocols are Phase 1 contract
  artifacts so Phase 2 and Phase 3 adapters do not invent their own call
  shapes. Phase 4 proves fake, unsupported, and queue-facing conformance
  against those protocols instead of introducing a second protocol shape.
- Import uses target-local identity and records source identity as provenance.
  Merge, overwrite, fork, and live-resume import policies are deferred.
- Offline evidence is not converted into a bundle before import. It remains an
  authority adapter that can share neutral importer/result models while keeping
  authority validation and mutation in `loom.authority.offline_import`.
- `RunExporter` and `RunImporter` are explicit callable protocols. They are not
  plugin loading, automatic dispatch, or external service integration.
- CLI command names are selected as `loom runs export`,
  `loom runs inspect`, and `loom runs import`, matching the landed
  `loom runs index/list/diff` grouping. Queue transfer evidence remains visible
  through queue/preflight/status formatting only where those existing surfaces
  consume delegated verification mappings.

## Conflicts And Tradeoffs

- **Shared protocol vs. local bundle simplicity:** portable-run exchange adds
  an abstraction before the first archive implementation, but it prevents local
  tar/manifest assumptions from leaking into offline evidence and future
  providers.
- **`loom.runs` ownership vs. import-light authority use:** keeping public APIs
  under `loom.runs` matches feature ownership, but neutral records may need a
  small adjacent module if authority/offline import would otherwise depend on
  archive/catalog behavior.
- **Strict manifest schema vs. forward compatibility:** strict top-level schema
  rejects ambiguous bundles, while explicit extension fields preserve future
  opaque refs without promising backend semantics.
- **Target-local identity vs. source identity preservation:** target-local
  identity avoids collisions and live-state confusion, while source identity is
  kept in provenance for audit and future mapping.
- **Readiness hooks vs. no live resume:** exposing blockers now creates a
  future attachment point, but the runner/planner still must reject migrated
  live continuation until later equivalence and rebasing policy exists.
- **Explicit unsupported adapters vs. speculative providers:** unsupported
  diagnostics are less exciting than placeholder provider implementations, but
  they avoid committing to protocols before real adapters exist.

## Maintainability Assessment

The plan is maintainable if it keeps four boundaries sharp:

- `loom.runs` owns user-facing bundle and portable-run operations, while lower
  store layers provide authoritative read models and local path facts.
- Neutral result/readiness records stay plain-data and import-light, especially
  for `loom.authority.offline_import`.
- Queue code receives transfer evidence as serialized mappings and does not
  parse bundle manifests or archives.
- CLI commands remain thin wrappers with formatting and exit-code behavior,
  not business logic.

The highest maintainability risks are `loom.runs` becoming a catch-all export
package, authority/offline import acquiring archive dependencies, queue
adapters importing bundle internals, and overly broad provider hooks before
real implementations exist.

## Extensibility Assessment

The v12 extensibility path is intentionally narrow:

- Future providers implement `RunExporter` and `RunImporter` over portable-run
  exchange records.
- Stage 14 plugin discovery can load those providers later without changing
  local bundle archive internals.
- Stage 15/16 external artifact interfaces can attach real backend semantics
  to extension fields that are opaque in v12.
- Future transfer handlers can fill the same transfer verification records
  without making queue own archive policy.
- Future live migrated resume can consume readiness facts only after target
  authority equivalence, artifact-ref rebasing, and planner reuse policy exist.

The plan should not expose more public protocol surface than it can validate
with local bundle, offline-evidence, fake, and unsupported adapters.

## Technical Debt Ledger

| Debt | Accepted For v12 Because | Revisit Trigger |
| --- | --- | --- |
| Local bundle is the only concrete storage/transport adapter | Roadmap defers remote stores, SSH/object-store transfer, encryption, signing, dedupe, and sync | A later transfer or remote artifact stage selects a concrete handler |
| `RunExporter` and `RunImporter` ship before real provider implementations | Stage 14 owns plugin discovery and later stages own external adapters | Plugin discovery or a concrete external adapter needs the protocols widened |
| Neutral importer/result model placement may require a small adjacent module | Authority offline import must stay import-light and archive-free | Plan review or implementation detects an import cycle or heavy import boundary |
| Offline import may keep compatibility shims | Existing v10 behavior and diagnostics are already public enough to preserve | Shared importer results fully cover authority diagnostics and migration can be done compatibly |
| Resume-readiness records ship before resume behavior | Future live migration needs stable facts, but v12 cannot prove target equivalence safely | Target-store equivalence, artifact rebasing, and authority continuation policy are designed |
| Transfer evidence exists before concrete transfer handlers | V11 queue needs evidence records, but transfer handlers are deferred | SSH/object-store/workspace staging support lands |

## Validation Strategy

The plan must preserve the examples and validation matrix confirmed in the
planning notes.

| Example or behavior | Primary owning phases | Validation obligation |
| --- | --- | --- |
| Metadata-only completed-run export | Phases 1 and 2 | Prove completed-run facts build portable export records and local bundle manifests without including payload bytes by default. |
| Bundle inspection without extraction | Phase 2 and Phase 5 | Prove API and CLI inspect read manifest summaries and optional checksum facts without extracting members. |
| Safe import into temporary collection | Phase 3 and Phase 5 | Prove unsafe paths, collisions, checksum mismatch, and failed validation reject before commit and leave no partial target state. |
| Offline evidence import through shared importer semantics | Phase 3 | Prove v10 strict rejection, replay events, diagnostics, authority mutation boundaries, and historical provenance remain compatible. |
| Resumable migration readiness report | Phase 3 | Prove import results carry status plus blocker codes and migrated live resume remains unsupported. |
| Delegated transfer evidence | Phase 4 | Prove `proven`, `unproven`, and `unsupported` records serialize to queue-consumable mappings. |
| Fake compatibility exporter/importer | Phases 1 and 4 | Prove the minimal protocols work over portable-run exchange records without external clients or plugin discovery. |
| Unsupported provider or transfer adapter | Phases 1 and 4 | Prove deferred provider/transport behavior raises `NotImplementedError` in Python handler paths or returns structured unsupported diagnostics at CLI/structured boundaries. |
| `loom runs export/inspect/import` CLI | Phase 5 | Prove text and JSON wrappers call public Python APIs and duplicate no store/archive logic. |

Required suite categories:

- Package/import-boundary tests for `loom.runs`, authority/offline import,
  queue, stores, CLI, plugins, and optional dependencies.
- Unit tests for models, manifest validation, archive path normalization,
  payload selection, diagnostics, readiness blockers, and transfer evidence.
- Contract tests for public record shapes, fake and unsupported adapters,
  queue-consumable evidence mappings, and CLI JSON envelopes where useful.
- Integration tests for export/inspect/import over temporary collections and
  existing offline-evidence fixtures.
- Limited e2e coverage for the happy-path local CLI workflow if current e2e
  conventions support it.
- No default network, real cluster, external service, or plugin tests.

## Implementation Workflow State

- Implementation-plan quality gate: passed on 2026-05-14
- Review pass: complete; local equivalent review run by managing Codex against
  `.codex/prompts/implementation-plan-review.md`
- Refinement pass: complete; protocol sequencing and stack-base notes clarified
- Confirmation review: complete; no blocking findings remain
- Automatic merge mode: enabled for later phase implementation
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Default phase base/target branch in this plan is `develop`. Each phase
  execution planner must recompute and record the actual stack predecessor and
  PR target before implementation; if an earlier phase is unmerged, branch from
  and target the recorded predecessor branch according to the stacked phase
  workflow.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `portable-run-exchange-contracts` | merged | `codex/portable-run-exchange-contracts` | [#146](https://github.com/samcantrill/loom/pull/146) | `loom.runs` models plus import-light neutral records and minimal protocols | Establish portable-run exchange, manifest, result, evidence, readiness, and importer/exporter protocol contracts | Package, unit, contract | Manifest models, fake/unsupported adapter records |
| 2 | `run-bundle-export-inspect` | merged | `codex/run-bundle-export-inspect` | [#147](https://github.com/samcantrill/loom/pull/147) | `loom.runs` export and archive helpers | Implement export, archive safety, and inspect without extraction | Unit, contract, integration | Metadata-only export, inspect safety |
| 3 | `run-bundle-import-offline-readiness` | in_progress | `codex/run-bundle-import-offline-readiness` | pending | `loom.runs` import plus `loom.authority.offline_import` adapter alignment | Implement safe import, offline-evidence alignment, provenance, and readiness blockers | Package, unit, contract, integration | Safe import, offline evidence, resume readiness |
| 4 | `transfer-evidence-protocols` | pending | `codex/transfer-evidence-protocols` | pending | Transfer evidence mappings, importer/exporter conformance, queue mapping tests | Publish queue-consumable transfer verification and explicit fake/unsupported protocol behavior | Package, unit, contract, narrow integration | Queue evidence, fake/unsupported adapters |
| 5 | `run-bundle-cli-docs-hardening` | pending | `codex/run-bundle-cli-docs-hardening` | pending | CLI, docs, final hardening | Expose `loom runs export/inspect/import`, document behavior, and run final validation | Package, unit, contract, integration, e2e where practical | CLI workflow, docs, final gate |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Plan quality gate | Workflow requirement | Local review, one refinement pass, and confirmation review completed on 2026-05-14 before Phase 1 starts | resolved |
| Roadmap planning blockers | `docs/roadmap/stage-12/planning.md` | None | resolved |

## Plan Quality Gate

- Status: passed
- Gate date: 2026-05-14
- Reviewer: managing Codex local review using the
  `.codex/prompts/implementation-plan-review.md` criteria. No separate reviewer
  subagent was used because this turn did not request delegated agent work.
- Review pass: complete; maintainability, extensibility, future compatibility,
  conflicting design choices, technical debt, test strategy, planning
  readiness, and reviewability were checked.
- Refinement pass: used; the plan now makes Phase 1 own the minimal
  `RunExporter`/`RunImporter` protocol contract and records the stacked-branch
  base/target recalculation rule before each phase execution plan.
- Confirmation review: complete; no blocking findings remain after the
  refinement.
- Budget status: review used, refinement used, confirmation used.
- Planning-readiness dependencies:
  - `docs/roadmap/stage-12/planning.md` records final planning confirmation.
  - Design-safety review passed on 2026-05-14.
  - No unresolved `blocked` or `needs discussion` planning decisions remain.
  - Examples, validation strategy, and phase shaping are specific enough to
    draft phases.
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
| Concern | Phase 1, Phase 4, `Key Design Choices` | The draft introduced `RunExporter`/`RunImporter` as a Phase 4 goal even though Phase 2 export and Phase 3 import adapters would need a stable adapter call shape earlier. That could force phase implementers to invent protocol behavior before the plan formally defines it. | Phase 1 now owns the minimal importer/exporter protocol contract alongside portable-run exchange records. Phase 4 is narrowed to queue-consumable transfer evidence, fake/unsupported adapter conformance, and structured unsupported behavior over the Phase 1 protocols. |
| Note | `Implementation Workflow State`, phase branch metadata | The phase tables list `develop` as the default base/target for all phases, but stacked continuation may require a later phase to branch from and target an unmerged predecessor. | The workflow state now records `develop` as the default only and requires each phase execution planner to recompute and record the actual stack predecessor and PR target before implementation. |

The confirmation review verified that the plan preserves the portable-run
exchange boundary from DAQ-10, the authority/offline-import boundary from
DAQ-5, queue plain-data evidence from DAQ-6, archive safety from DAQ-2 and
DAQ-3, and fail-closed migration-resume behavior from DAQ-7.

## Phased Implementation

### Phase 1: Portable Exchange And Bundle Manifest Contracts

- Status: merged
- Branch: `codex/portable-run-exchange-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/portable-run-exchange-contracts`
- PR: [#146](https://github.com/samcantrill/loom/pull/146)
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

**Goal**

Establish adapter-neutral portable-run exchange records plus local bundle
manifest, import/export result, transfer evidence, readiness, diagnostics, and
minimal importer/exporter protocol contracts without archive I/O or CLI
behavior.

**Scope**

- Public or import-light value models for portable source identity, target
  identity policy, adapter identity, selected entries, payload refs,
  diagnostics, import/export records, and extension fields.
- Local bundle manifest models with format version, entry kind, checksums,
  payload-selection metadata, warnings, and opaque extension fields.
- Result models for export, inspection, import, transfer evidence, and
  migration-resume readiness.
- Minimal explicit `RunExporter` and `RunImporter` protocols over
  portable-run exchange records and adapter result envelopes.
- Minimal unsupported-provider or unsupported-transfer diagnostic records where
  v12 can define stable result behavior.
- Placement decision for neutral records if `loom.runs` would create authority
  import-boundary risk.
- Package/import-boundary guardrails for `loom.runs`, authority/offline import,
  queue, stores, CLI, plugins, and optional dependencies.

**Out Of Scope**

- Archive read/write implementation.
- Local collection import/extraction.
- CLI commands.
- Real external providers or transfer handlers.
- Provider-specific adapters beyond local bundle, offline-evidence, fake, and
  unsupported contract fixtures.

**Acceptance Criteria**

- Public records round-trip through plain data.
- Manifest version and unsupported schema diagnostics are structured.
- Unknown top-level manifest fields are rejected or diagnosed as unsupported;
  explicit extension fields preserve opaque data.
- Local bundle and offline evidence can both map to portable-run exchange
  records without either becoming the other's storage format.
- Phase 2 and Phase 3 can implement concrete adapters against the Phase 1
  protocol shape without defining a new adapter interface.
- Deferred provider hooks expose structured unsupported diagnostics or
  `NotImplementedError` behavior.
- Import-boundary tests prove neutral records do not pull archive/catalog
  behavior into authority, queue, stores, or CLI modules.

**Test Expectations**

- Package: import-boundary coverage for `loom.runs`, authority/offline import,
  queue, stores, CLI, plugins, and optional dependencies.
- Unit: model validation, serialization, manifest version handling, readiness
  blocker codes, and diagnostic records.
- Contract: plain-data compatibility for local bundle, offline-evidence, fake,
  and unsupported adapter records plus minimal importer/exporter protocol
  signatures.
- Integration: import smoke only if needed to prove cheap imports.
- E2E: not required.
- Opt-in: none.

**Design Impact**

This is the public contract and persisted manifest foundation. Phase 1 must
avoid overfitting public exchange records to the local archive adapter.

**Future Compatibility**

The contract must leave room for plugin-loaded providers, external/remote refs,
future transfer handlers, and live migration readiness without claiming those
behaviors now.

**Alternatives Rejected**

- CLI-owned models.
- Store-owned archive contracts.
- Permissive manifest schemas without strict version boundaries.
- Bundle archives as the base provider protocol.
- Offline evidence forced to serialize as a bundle before import.
- Metric-aware or external-service-specific exporter contracts.

**Debt Introduced**

- The schema starts conservative and may need widening once real providers or
  external artifact contracts arrive.
- Abstract hooks may remain unsupported placeholders if no stable v12 behavior
  exists beyond diagnostics.

**Reviewability**

Keep this phase model/API focused with no archive I/O, CLI, or authority
mutation changes beyond import-boundary-safe adapter records.

**Notes**

- If neutral model placement under `loom.runs` creates import-boundary pressure,
  document the adjacent import-light module choice in the phase execution plan.

**Completion Summary**

- Phase execution plan added at
  `docs/roadmap/stage-12/phases/portable-run-exchange-contracts.md`.
- PR opened and merged:
  [#146](https://github.com/samcantrill/loom/pull/146), targeting `develop`
  from `codex/portable-run-exchange-contracts`.
- Merge evidence: GitHub CI `checks` passed; PR target verified as `develop`;
  PR merged on 2026-05-14 with merge commit
  `a57f78568e0c4b9a2345d7cc847ae125cb2328f4`.
- Implementation summary: added import-light portable-run exchange records,
  strict local bundle manifest records, shared diagnostics/result/readiness
  envelopes, transfer evidence placeholders, and minimal
  `RunExporter`/`RunImporter` protocols under `loom.runs`.
- Tests and validation: targeted Phase 1 pytest set passed with 53 tests;
  targeted Ruff and Pyright passed; `make validate-pr` passed outside the
  sandbox; `make test-summary` passed with overall 1910 passed, 0 failed, 0
  errors, 18 skipped, and 1497 deselected.
- Follow-up notes: no successor branch depended on the Phase 1 branch at merge
  time; branch cleanup was safe.

### Phase 2: Export, Archive Safety, And Inspect

- Status: merged
- Branch: `codex/run-bundle-export-inspect`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-bundle-export-inspect`
- PR: [#147](https://github.com/samcantrill/loom/pull/147), merged
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

**Goal**

Implement metadata-only export by default, explicit payload/log inclusion,
archive member safety, checksum/size reporting, and inspect without extraction.

**Scope**

- Build portable-run export records from completed-run metadata and selected
  materialized refs.
- Implement the local bundle exporter as a concrete adapter over the Phase 1
  `RunExporter` protocol shape.
- Materialize local bundle manifests from portable-run export records.
- Standard-library local archive write/read helpers.
- Path traversal, symlink, duplicate/colliding member, missing payload,
  checksum mismatch, unexpected large payload, and active-run-changed
  diagnostics.
- Bundle inspection API that reads manifest summaries and optional checksum
  evidence without extraction.
- Convenience APIs through `RunCatalog` or public `loom.runs` functions.

**Out Of Scope**

- Import into run collections.
- Offline evidence alignment.
- CLI commands.
- New or incompatible importer/exporter protocol design.
- Remote payload downloads, external-ref validation, or credential handling.

**Acceptance Criteria**

- A synthetic completed run can be exported through portable-run records and
  then materialized as a local bundle.
- The local bundle export path conforms to the Phase 1 exporter protocol
  contract and result envelope.
- Metadata-only export is the default and does not include payload bytes.
- Explicit payload/log flags broaden selection intentionally and report
  size/path facts.
- Inspect reports manifest, run identity, status, stages, artifacts, payload
  counts/sizes, warnings, and optional checksum status without extracting.
- Unsafe archive members or changing run reads produce structured diagnostics.

**Test Expectations**

- Package: maintain Phase 1 boundaries.
- Unit: path normalization, manifest builder, payload selection, checksum and
  size diagnostics.
- Contract: inspection result shape where useful.
- Integration: export/inspect over temporary completed runs and unsafe bundle
  fixtures.
- E2E: not required.
- Opt-in: none.

**Design Impact**

This phase fixes archive safety behavior that import and CLI must reuse.

**Future Compatibility**

Remote/external refs remain metadata-only and opaque; later materialization
handlers can attach explicit behavior without changing manifest fundamentals.

**Alternatives Rejected**

- Including all payloads by default.
- Adding compression dependencies before a concrete need.
- Inspecting by extraction.
- Best-effort acceptance of unsafe members.

**Debt Introduced**

- No signed, encrypted, deduplicated, remote-materialized, or synchronized
  bundle behavior.

**Reviewability**

Review should focus on the export data flow, archive safety helpers, and
inspect-without-extraction proof.

**Notes**

- Export must read authority-backed completed-run facts where available and
  treat local materialization as payload/projection input, not lifecycle truth.

**Completion Summary**

- Phase execution plan:
  `docs/roadmap/stage-12/phases/run-bundle-export-inspect.md`.
- PR: [#147](https://github.com/samcantrill/loom/pull/147), merged into
  `develop` on 2026-05-14 with merge commit
  `143297c149f12bbba7d4135f45a05e1a03f4867a`.
- Implementation summary: added metadata-backed export-record assembly,
  strict local bundle writing, `RunExporter`-conforming local exporter,
  traversal-safe archive member validation, metadata-only default export,
  explicit selected-payload inclusion as regular archive members, and
  inspect-without-extraction checksum diagnostics under `loom.runs`.
- Tests and validation: targeted Phase 2 pytest set passed with 51 tests;
  targeted Ruff and Pyright passed; `make validate-pr` passed outside the
  sandbox; `make test-summary` passed with overall 1918 passed, 0 failed, 0
  errors, 18 skipped, and 1505 deselected; GitHub CI `checks` passed before
  merge.
- Follow-up notes: Phase 3 should reuse the archive path validation and
  manifest reader rather than inventing a separate import safety path. No
  successor branch depended on the Phase 2 branch at merge time; remote branch
  cleanup was safe and completed.

### Phase 3: Import, Offline Alignment, And Resume Readiness

- Status: in_progress
- Branch: `codex/run-bundle-import-offline-readiness`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-bundle-import-offline-readiness`
- PR: pending
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

**Goal**

Implement safe bundle and offline-evidence import through shared portable-run
import records with target-local identity, source provenance, collision
rejection, v10 offline-import compatibility, and resume-readiness blocker
reporting.

**Scope**

- Local bundle import adapter that validates source evidence and converts it
  into portable-run import records.
- Offline-evidence adapter alignment that shares neutral importer/result
  semantics while preserving authority validation and mutation boundaries.
- Local bundle and offline-evidence adapters conform to the Phase 1
  `RunImporter` protocol shape without turning offline evidence into a bundle
  archive format.
- Target-local identity resolution, source provenance, bundle/evidence
  identity, workspace/store facts, and collision rejection.
- Temporary staging and safe commit behavior for local run collections.
- Catalog refresh or stale marking after import.
- Resume-readiness records with status and machine-readable blockers.
- Fail-closed migrated-live-resume diagnostics where continuation surfaces can
  observe imported historical state.

**Out Of Scope**

- Live migrated resume.
- Merge, fork, overwrite, or sync import policies.
- Authority mutation outside explicit authority import adapters.
- Cross-workspace synchronization or remote payload materialization.
- New or incompatible importer/exporter protocol design.

**Acceptance Criteria**

- Bundle import rejects unsafe paths, unsupported manifests, checksum mismatch,
  and collisions before commit.
- The local bundle and offline-evidence import paths conform to the Phase 1
  importer protocol contract and result envelope.
- Imported copies use target-local identity and record source identity in
  provenance.
- Offline evidence import remains compatible with v10 strict validation,
  collision rejection, replay events, diagnostics, and historical-only
  provenance while sharing importer result semantics.
- Offline evidence is not forced through local bundle archive serialization.
- Import results report readiness status plus blockers, and live migrated
  resume remains unsupported.

**Test Expectations**

- Package: authority/offline import does not import archive helpers,
  `RunCatalog` behavior, CLI, queue controllers, plugins, or optional clients.
- Unit: import policy/result/readiness diagnostics and blocker codes.
- Contract: importer result shape, adapter identity, unsupported diagnostics,
  source/target provenance, and collision policy.
- Integration: temporary collection import, collision rejection, offline
  evidence regression tests, replay event preservation, catalog refresh/stale
  behavior.
- E2E: not required.
- Opt-in: none.

**Design Impact**

This phase locks migration/import semantics and the separation between source
audit identity and target executable identity.

**Future Compatibility**

Future live migration can consume readiness facts only after target authority
equivalence, artifact-ref rebasing, fingerprint equivalence, and planner reuse
policy are designed.

**Alternatives Rejected**

- Preserving source `run_uri` as active target identity.
- Overwriting or merging collisions by default.
- Best-effort migrated live resume.
- Moving authority mutation into local bundle code.
- Converting offline evidence into bundles before authority import.

**Debt Introduced**

- Compatibility shims may remain until neutral importer results fully cover all
  authority diagnostics.

**Reviewability**

Review should focus on import safety, v10 compatibility preservation, and
readiness-blocker behavior separately from export archive code.

**Notes**

- If a refactor touches existing offline-import APIs, the phase execution plan
  must list exact public compatibility expectations and regression tests.

**Completion Summary**

- Phase execution plan:
  `docs/roadmap/stage-12/phases/run-bundle-import-offline-readiness.md`.
- Implementation started from updated `origin/develop` after Phase 2 merge.

### Phase 4: Transfer Evidence And Importer/Exporter Protocols

- Status: pending
- Branch: `codex/transfer-evidence-protocols`
- Worktree: `/home/samcantrill/work/loom-worktrees/transfer-evidence-protocols`
- PR: pending
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

**Goal**

Add queue-consumable transfer verification mappings and prove fake,
unsupported, and structured adapter behavior over the Phase 1
importer/exporter protocols without concrete transfer handlers or external
providers.

**Scope**

- Transfer verification serialization and mapping helpers for `proven`,
  `unproven`, and `unsupported` checks.
- Plain-data mappings suitable for `LaunchContract.delegated_verification`.
- Fake adapter contract coverage over the Phase 1 `RunExporter` and
  `RunImporter` protocols.
- Unsupported provider, exporter/importer, and transfer adapter contracts.
- Unsupported transfer diagnostics for Python and structured/CLI consumers.

**Out Of Scope**

- SSH, object-store, remote workspace, automatic staging, or network handlers.
- Plugin discovery or automatic exporter dispatch.
- MLflow, DVC, W&B, static report, or service-specific adapters.
- Queue archive parsing or queue-owned bundle schemas.

**Acceptance Criteria**

- Queue/delegated-launch surfaces can reference transfer evidence as plain
  mappings without importing bundle archive internals.
- Fake importer/exporter tests demonstrate the Phase 1 protocol contracts.
- Unsupported transfer/provider handlers fail explicitly through
  `NotImplementedError` or structured unsupported diagnostics.
- Queue contract tests cover `proven`, `unproven`, and `unsupported` evidence
  shape.

**Test Expectations**

- Package: queue control modules do not import bundle archive internals.
- Unit: transfer evidence serialization, queue mapping, and unsupported
  diagnostics.
- Contract: queue-consumable evidence shape plus fake and unsupported
  importer/exporter adapters.
- Integration: narrow queue/preflight evidence formatting only if needed.
- E2E: not required.
- Opt-in: none.

**Design Impact**

This phase closes the v11 transfer-evidence handoff while keeping queue
scheduling independent from bundle/archive policy.

**Future Compatibility**

Future concrete transfer handlers can populate the same evidence records, and
future provider adapters can implement the same protocols without depending on
local bundle archives.

**Alternatives Rejected**

- Queue-owned bundle schemas.
- Bundle export depending on queue.
- Human-only transfer evidence.
- Automatic exporter dispatch.
- Speculative provider adapters without structured unsupported behavior.

**Debt Introduced**

- Transfer handlers and provider adapters remain unsupported until later stages
  select concrete behavior.
- Protocols may need widening when real providers arrive.

**Reviewability**

Keep the phase contract-heavy and focused on evidence mappings, protocol
conformance, and package boundaries.

**Notes**

- Any queue-facing change should be limited to consumption or display of plain
  delegated-verification evidence.

**Completion Summary**

- Pending.

### Phase 5: CLI, Docs, Hardening, And Final Validation

- Status: pending
- Branch: `codex/run-bundle-cli-docs-hardening`
- Worktree: `/home/samcantrill/work/loom-worktrees/run-bundle-cli-docs-hardening`
- PR: pending
- Base branch: `develop`
- Target branch: `develop`
- Workflow path: expanded path

**Goal**

Expose the confirmed bundle workflows through thin `loom runs` CLI commands,
update docs, harden diagnostics, and run final validation.

**Scope**

- Add `loom runs export`, `loom runs inspect`, and `loom runs import` under the
  current `loom runs index/list/diff` command group.
- Text and JSON result envelopes for export, inspect, and import.
- CLI diagnostics for unsupported transfer/provider behavior, unsafe bundles,
  import collisions, checksum mismatch, unsupported schemas, stale catalog
  state, and resume-blocked imports.
- Documentation for metadata-only defaults, inspect-without-extraction,
  payload/log flags, target-local identity, source provenance, local bundle
  versus portable-run exchange, offline-evidence alignment, unsupported
  providers, and live-resume deferral.
- Final package/import-boundary sweep and final PR evidence.

**Out Of Scope**

- New external integrations.
- Network, cluster, or provider tests.
- Automatic exporter dispatch.
- A top-level `loom bundle` command family unless a phase blocker proves
  `loom runs` cannot host the commands.

**Acceptance Criteria**

- CLI wrappers call public Python APIs and duplicate no bundle/store logic.
- `loom runs export`, `loom runs inspect`, and `loom runs import` support text
  and JSON output.
- Docs explain conservative defaults, archive safety, import provenance,
  historical-only import behavior, and all major deferrals.
- `make validate-pr` and `make test-summary` run successfully or blockers are
  recorded.

**Test Expectations**

- Package: final import-boundary sweep.
- Unit: formatting helpers where useful.
- Contract: JSON envelope and diagnostic expectations where useful.
- Integration: CLI export/inspect/import text and JSON flows.
- E2E: limited happy-path local bundle workflow if existing conventions support
  it.
- Opt-in: none.

**Design Impact**

This phase makes the public CLI surface visible and closes documentation gaps.

**Future Compatibility**

Later aliases, plugin-loaded commands, or provider-specific CLI wrappers can
call the same public Python APIs without changing the core command behavior.

**Alternatives Rejected**

- Business logic in CLI.
- Top-level command family without current-surface justification.
- External-service examples in core docs.

**Debt Introduced**

- CLI remains limited to built-in local bundle and aligned offline-evidence
  behavior; provider-specific CLI UX is deferred.

**Reviewability**

Review should focus on thin CLI boundaries, clear docs, final diagnostics, and
final validation evidence.

**Notes**

- The selected command names intentionally match the current landed CLI:
  `loom runs index/list/diff` already owns run collection inspection, while
  `loom queue preflight/start/status/cancel/drain-foreground` remains the queue
  operational surface.

**Completion Summary**

- Pending.

## Cross-Phase Review Notes

- Phase 1 must not implement archive I/O early.
- Phase 1 must define the minimal importer/exporter protocol shape that Phases
  2 and 3 implement; Phase 4 must not introduce a second protocol or widen the
  Phase 1 protocols without explicit compatibility justification.
- Phase 2 must not implement import behavior early.
- Phase 3 must not enable live migrated resume or weaken v10 offline import.
- Phase 4 must not add concrete transfer/provider implementations.
- Phase 5 must not duplicate business logic in CLI.
- Every phase execution plan must record design impact, future compatibility,
  alternatives rejected, debt introduced, reviewability, and phase budget
  status before implementation starts.
- Full PR preparation for every phase must run or justify `make validate-pr`
  and `make test-summary`.

## Final Approval

- Approval status: approved for Phase 1 execution planning after the Stage 12
  plan quality gate passed on 2026-05-14.
- Approved scope: adapter-neutral portable-run exchange, local bundle export,
  inspect/import safety, offline-evidence alignment, transfer evidence,
  importer/exporter protocol contracts, CLI wrappers, docs, and final
  hardening as phased above.
- Accepted risks:
  - Minimal protocols may need widening when real adapters arrive.
  - Neutral record placement may need adjustment to protect import boundaries.
  - Deferred provider and transfer hooks remain unsupported in v12.
  - Resume-readiness records ship before any live resume implementation.
- Deferred items:
  - concrete transfer handlers;
  - remote payload materialization;
  - signed/encrypted/deduplicated/synchronized bundles;
  - plugin discovery and provider adapters;
  - external service exporters/importers;
  - automatic post-run dispatch;
  - live migrated resume.
