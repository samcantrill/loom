# Roadmap Stage 16 Implementation Plan: Artifact Payload Materialization

Status: draft
Roadmap stage: `v16`
Planning document: `docs/roadmap/stage-16/planning.md`
Workflow: `.codex/workflows/roadmap-stage-implementation.md`
Target branch: `develop`
Current phase: Phase 5 in progress
Blockers:

- None. Implementation-plan quality gate passed on 2026-05-15 after
  `loom_plan_reviewer` review, bounded refinement, and confirmation review.

## Summary

- Goal: implement explicit artifact payload materialization on top of landed
  Stage 15 artifact records, backend contracts, immutable lookup helpers,
  artifact backend preflight targets, and run exchange metadata preservation.
- Source functionality-agreement gate: confirmed in
  `docs/roadmap/stage-16/planning.md` with FR-1 through FR-9 closed.
- Approved behavior: metadata-only workflows remain the default; local
  materialization is copy-only; unsupported non-copy policies and unsupported
  backend operations fail closed through structured results; bundle
  export/import is the primary workflow; no real backend family is selected;
  preflight remains cheap by default with explicit expensive probes only.
- Source behavior confirmation: complete on 2026-05-15.
- Key design constraints: keep `loom` domain-neutral, dependency-light,
  import-light, fake-backend-first, redaction-safe, and strict plain-data
  serializable. Do not add cloud/tracking SDKs or network work to default
  imports, default preflight, catalog, inspect, export, or import paths.
- Source design-agreement gate: confirmed DAQ-1 through DAQ-9. Shared
  operation/evidence value objects live in new import-light `loom.operations`;
  store-owned materialization protocols live under `loom.pipeline.stores`;
  `loom.runs` and `loom.diagnostics` consume and project those contracts.
- Future-roadmap impact: Stage 17/18 can use copy materialization and derived
  staging facts for container/HPC payload placement; Stage 19 can wrap
  operation results with retry/timeout policy; Stage 20 can use derived
  materialized/staging records for cleanup without deleting authoritative
  external truth.
- Reusable interface, adapter, or protocol assumptions: Stage 16 shares only
  plain operation/evidence primitives and projection helpers. Authority import,
  portable run exchange, preflight presentation, and payload movement remain
  separate protocols with separate ownership and failure semantics.
- Examples covered: local copy materialization; metadata-only bundle
  export/import; explicit fake-backend materialization in bundle workflows;
  read-only and writable object-store-style fake behavior; tracking-system
  indirection fake behavior; unsupported real-backend handles.
- Source phase shaping: five phases confirmed in the planning artifact.
- Source plan quality gate: passed on 2026-05-15.
- Out of scope: first-party S3/GCS/Azure/MLflow/DVC/W&B/HTTP adapters;
  provider SDKs; credential lifecycle management; transparent downloads;
  automatic global cache lookup; partial-stage reuse; remote catalog services;
  retries/timeouts beyond result evidence; deletion, retention, and GC.

## Goal

Stage 16 turns Stage 15 metadata contracts into an explicit payload-operation
surface. Users and APIs should be able to ask Loom to copy, materialize,
publish, upload, download, or verify payload bytes only when the operation is
selected and backend capabilities allow it. Metadata-only catalog, inspect,
bundle export, bundle import, and run exchange behavior must continue to work
without credentials, optional dependencies, or payload access.

The plan intentionally starts with shared operation/evidence primitives before
adding materialization behavior. That addresses the user-raised duplication
concern without collapsing authority lifecycle import, portable exchange,
diagnostics, and payload movement into one subsystem.

## Context

Stage 15 has landed and is the implementation baseline:

- `loom.artifacts` owns strict metadata value objects:
  `ArtifactStoreRef`, `ArtifactLocationSummary`,
  `ExternalArtifactDeclaration`, `PublishedArtifactRecord`,
  `ImmutableArtifactLookupRequest`, and `ImmutableArtifactLookupResult`.
- `loom.pipeline.stores.artifact_backends` owns artifact-store backend
  descriptors, factories, handlers, registries, operation capability records,
  diagnostics, and structured unsupported/unknown operation results.
- `loom.pipeline.stores.immutable_artifacts` owns metadata-only immutable
  validation, capability admission, and explicit lookup helpers.
- `loom.diagnostics` owns artifact backend preflight targets and cheap
  metadata/config/capability checks.
- `loom.runs` preserves Stage 15 artifact summaries through portable run
  exchange, local bundle export, inspect, and import without moving payloads.

Focused Stage 15 verification passed on 2026-05-15:

```text
uv run pytest tests/contracts/test_artifact_store_backend_contract.py \
  tests/contracts/test_external_artifact_records_contract.py \
  tests/contracts/test_immutable_artifact_semantics_contract.py \
  tests/contracts/test_backend_diagnostics_contract.py \
  tests/contracts/test_run_bundle_export_contract.py \
  tests/contracts/test_run_bundle_import_contract.py \
  tests/contracts/test_run_exchange_contract.py \
  tests/unit/loom/pipeline/stores/test_artifact_backends.py \
  tests/unit/loom/pipeline/stores/test_immutable_artifacts.py \
  tests/unit/loom/diagnostics/test_artifact_backend_preflight.py \
  tests/unit/loom/runs/test_artifact_metadata.py \
  tests/unit/loom/runs/test_bundle_export.py \
  tests/unit/loom/runs/test_bundle_import.py \
  tests/unit/loom/runs/test_run_exchange_models.py
```

Result: 59 passed.

## Planning Readiness

- Source planning notes: `docs/roadmap/stage-16/planning.md`
- Functionality and behavior baseline: complete. The notes lock explicit
  payload movement, metadata-only defaults, copy-only local behavior, fake
  backend validation, no real backend, bundle/export/import priority, cheap
  default preflight, and narrow CLI policy.
- Design-safety review: passed. DSR-1 through DSR-7 are recorded, and the
  Stage 15 landed-contract readiness blocker has been resolved.
- Stage 15 source/API recheck: complete on 2026-05-15 with focused tests.
- Examples and validation strategy: complete. Validation is fake-backend-first,
  no-network by default, and includes import-boundary tests, copy-only tests,
  metadata-only bundle tests, and unsupported-result tests.
- Phase shaping: complete. Five phases are recorded below.
- Implementation readiness blockers from planning: none.
- Accepted risks and revisit triggers:
  - No real backend family is selected. Revisit when a concrete backend need
    appears or fake object-store/tracking-system scenarios cannot share one
    handler/result shape.
  - `loom.operations` becomes a public import path. Revisit if it starts
    importing subsystem code, exposing lifecycle protocols, or needing root
    `loom.__init__` exports.
  - Bundle operation evidence should project through landed Stage 15 exchange
    records. Revisit if Phase 4 proves a narrow schema revision is required.

## Desired Outcome

When all phases are complete:

- `loom.operations` provides a small public, import-light vocabulary for
  adapter identity, operation status, diagnostics, evidence checks, redacted
  details, unsupported/not-implemented results, and strict plain-data
  projection.
- `loom.pipeline.stores` exposes artifact materialization request/result
  records, copy-only local materialization behavior, derived
  materialized/staging records, checksum evidence, and store-owned handler
  contracts for payload operations.
- Fake backends prove publish/materialize/upload/download/verify paths across
  object-store-style and tracking-system-style scenarios without optional SDKs.
- Bundle export/import can explicitly materialize supported payloads while
  metadata-only export/import remains the default and never downloads
  implicitly.
- Preflight can report materialization readiness for selected operations while
  default checks remain cheap and side-effect-light.
- Public API and narrow user-facing handles return clear structured
  unsupported or not-implemented results for skipped real backends, non-copy
  local policies, and missing capabilities.

## Non-Goals

- No real cloud, HTTP, DVC, MLflow, W&B, or tracking-system backend
  implementation.
- No provider SDK dependency in the default install.
- No implicit payload movement during catalog, inspect, export, import, or
  preflight.
- No credential manager, token refresh, secret storage, or remote account
  configuration lifecycle.
- No global content-addressed cache, distributed locking, transparent reuse,
  partial-stage reuse, or remote run catalog service.
- No retry/timeout policy beyond recording operation status and diagnostics.
- No cleanup, deletion, retention, or garbage-collection policy.
- No live controller-to-controller migration, authority merge/fork policy, or
  migrated resume semantics.

## Constraints

- Follow `docs/structure.md` boundaries and `docs/GLOSSARY.md` vocabulary.
- Keep authored configs trusted, but keep persisted metadata and diagnostics
  redacted and shareable.
- Keep `loom.artifacts` as metadata-only value objects. It must not import
  stores, diagnostics, runs, plugins, CLI, optional SDKs, or transfer handlers.
- Keep materialization policy under `loom.pipeline.stores`. Store modules may
  import `loom.artifacts`, `loom.operations`, and neutral helpers, but must not
  import `loom.runs`, `loom.diagnostics`, CLI modules, plugin discovery, or
  optional backends.
- Keep `loom.runs` as the portable-run exchange owner and a consumer of public
  artifact/store/operation contracts.
- Keep `loom.diagnostics` as the preflight presentation owner and a consumer of
  readiness/materialization summaries.
- Keep `loom.plugins` explicit. Stage 16 does not auto-discover or auto-load
  backend plugins because materialization APIs exist.

## Design Principles

- Metadata-only by default. Payload bytes move only when an API option or
  narrow CLI flag asks for movement.
- Fail closed. Unsupported, unknown, missing-backend, missing-credential,
  unsafe-path, checksum-mismatch, and partial-staging paths return structured
  diagnostics instead of falling back silently.
- Derived state stays derived. Staging, cache, and materialized locations are
  not authoritative artifact truth and do not mutate authority lifecycle state.
- Generic before provider-specific. Fake backends pressure-test the contract;
  real adapters remain future work.
- Projection over ownership collapse. Shared primitives reduce duplicated
  status/diagnostic/evidence shapes, but subsystem protocols remain separate.

## Key Design Choices

| Decision | Selected approach | Consequence |
| --- | --- | --- |
| Shared operation vocabulary | Add narrow `loom.operations` value objects and projection helpers first | Later phases reuse one status/evidence/diagnostic vocabulary without making a universal lifecycle protocol |
| Materialization ownership | Add request/result/protocol behavior under `loom.pipeline.stores` | Payload movement stays near artifact-store policy and away from artifacts, runs, diagnostics, and CLI presentation |
| Local policy | Stage 16 always copies; other policies return unsupported/not implemented | Behavior is portable across filesystems, bundles, Docker, and HPC; future policy handles remain explicit |
| Backend selection | No real backend family in Stage 16 | Default install stays dependency-light; fake backend coverage must be strong |
| Bundle schema | Prefer generic operation evidence projection over landed Stage 15 exchange records; use a narrow schema revision only if necessary | Bundles remain provider-neutral and metadata-only by default |
| Preflight | Cheap by default; expensive probes require explicit request selectors | CI and local default checks stay deterministic and network-free |
| CLI | Limit CLI changes to frequent expected workflows, especially existing `runs export`, `runs import`, and `runs inspect` presentation if the API is mature | No broad provider CLI or low-frequency command surface |

## Conflicts And Tradeoffs

- A new public `loom.operations` import path improves consistency but creates
  API surface. Scope is constrained to plain-data value objects and projection
  helpers, with no root export in Stage 16.
- Fake-backend-only validation keeps dependencies and CI lean but cannot prove
  every first-provider edge case. The fake scenarios must include object
  storage, tracking-system indirection, read-only, writable, unsupported,
  failure, checksum mismatch, and redaction behavior.
- Copy-only local materialization is less efficient than hardlinks, symlinks,
  reflinks, or cache promotion, but it is safer across filesystems and later
  container/HPC workflows.
- Bundle materialization is user-important enough to deserve narrow public
  handles, but default bundle operations must remain metadata-only and
  credential-free.

## Maintainability Assessment

The staged structure is maintainable because it isolates the public vocabulary
first, then builds local behavior, fake backend behavior, exchange/preflight
integration, and user-facing finalization in separate PRs. The riskiest
maintainability issue is allowing `loom.operations` to grow into a generic
subsystem framework. Phase 1 must record stop conditions and package tests
that enforce import direction.

## Extensibility Assessment

The plan keeps future real backends, non-copy local policies, Stage 19
reliability policy, and Stage 20 cleanup possible without requiring Stage 16
to implement them. Future adapters should implement store-owned handler
contracts and return the same operation evidence used by bundles and preflight.

## Technical Debt Ledger

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No real backend proof in Stage 16 | Avoids optional SDKs and provider overfitting without a concrete downstream need | User supplies a backend requirement, or fake backend personalities cannot share one generic handler/result shape |
| `loom.operations` public path starts before all consumers exist | Needed to avoid multiplying result/diagnostic vocabularies in Stage 16 | Module imports subsystem code, exposes lifecycle protocols, or grows beyond value objects/projections |
| Future local policies are represented before implementation | Avoids later incompatible request/result changes | A later stage selects hardlink, symlink, reflink, move, cache-promote, or staging policy |
| Bundle operation-evidence projection may need schema refinement | Landed Stage 15 exchange records are metadata-first and generic | Phase 4 proves extension/result fields cannot represent operation evidence clearly |

## Implementation Workflow State

- Implementation-plan quality gate: passed
- Review pass: complete by `loom_plan_reviewer`; no blocking findings
- Refinement pass: complete for catalog scope and per-phase test-summary
  evidence requirements
- Confirmation review: complete by `loom_plan_reviewer`; no remaining blocking
  findings
- Automatic merge mode: enabled
- Worktree root: `/home/samcantrill/work/loom-worktrees`
- Default phase base/target: `develop`; each phase execution planner must
  recompute and record the actual stack predecessor and PR target before
  creating its worktree.
- Phase status vocabulary: `pending`, `in_progress`, `pr_open`, `approved`,
  `merged`, `blocked`
- Workflow path: expanded path is expected for every phase because Stage 16
  creates public records/protocols and crosses artifacts, stores, runs,
  diagnostics, CLI, and package import boundaries.

## Phase Index

| Phase | Slug | Status | Branch | PR | Ownership | Goal | Validation | Examples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `shared-operation-evidence-contracts` | merged | `codex/shared-operation-evidence-contracts` | [#166](https://github.com/samcantrill/loom/pull/166) | `loom.operations`, narrow compatibility projections | Add shared operation/evidence value objects and bounded adoption | Unit/contract/package import-boundary tests, `make validate-pr`, `make test-summary` | Unsupported operation, checksum evidence, redacted diagnostic |
| 2 | `local-materialization-copy-records` | merged | `codex/local-materialization-copy-records` | [#167](https://github.com/samcantrill/loom/pull/167) | `loom.pipeline.stores`, public store exports | Add materialization records and copy-only local behavior | Store unit/contract/integration tests, `make validate-pr`, `make test-summary` | Local copy, checksum mismatch, unsupported non-copy policy |
| 3 | `fake-backend-payload-operations` | merged | `codex/fake-backend-payload-operations` | [#168](https://github.com/samcantrill/loom/pull/168) | store backend protocols and fake handlers | Add fake publish/materialize/upload/download/verify operations | Backend unit/contract tests, `make validate-pr`, `make test-summary` | Object-store-style and tracking-system-style fake scenarios |
| 4 | `bundle-preflight-materialization` | merged | `codex/bundle-preflight-materialization` | [#169](https://github.com/samcantrill/loom/pull/169) | `loom.runs`, `loom.diagnostics`, conditional catalog ownership, narrow CLI if warranted | Integrate explicit materialization into bundles/import/preflight and catalog only when explicitly opted in | Run exchange, diagnostics, conditional catalog, CLI/API tests, `make validate-pr`, `make test-summary` | Metadata-only default, explicit fake materialization |
| 5 | `no-backend-user-facing-handles` | in_progress | `codex/no-backend-user-facing-handles` | pending | docs, examples, package/API hardening | Finalize no-backend decision, docs, unsupported handles, and narrow user-facing affordances | Package/docs/contracts/full PR gate and `make test-summary` | No optional SDK import, unsupported real backend handle |

## Implementation Readiness Blockers

| Blocker | Source | Required resolution | Status |
| --- | --- | --- | --- |
| Plan quality gate | Repository workflow | Review, bounded refinement, and confirmation review completed on 2026-05-15; no blocking findings remain | resolved |

## Phase 1: Shared Operation And Evidence Contracts

Status: merged
Slug: `shared-operation-evidence-contracts`
Branch: `codex/shared-operation-evidence-contracts`
Worktree: `/home/samcantrill/work/loom-worktrees/shared-operation-evidence-contracts`
PR: [#166](https://github.com/samcantrill/loom/pull/166)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates public API surface and
touches shared projection contracts

### Scope

- Goal: add the bounded shared operation/evidence vocabulary that later Stage
  16 materialization, run exchange projections, diagnostics, and future
  backend adapters can reuse.
- Files/modules owned:
  - new `src/loom/operations.py` or `src/loom/operations/` package
  - package import-boundary tests
  - focused unit and contract tests
  - narrow compatibility projection helpers in `loom.runs` or
    `loom.diagnostics` only if dependency direction remains clean
- Behavior implemented:
  - Strict plain-data records for adapter identity, operation status,
    diagnostic severity, operation diagnostics, evidence checks, unsupported
    or not-implemented operation summaries, redacted details, and result
    projection.
  - Serialization and unknown-field validation consistent with existing Loom
    value records.
  - Redaction-safe detail helpers that do not serialize backend clients,
    credentials, or raw provider exceptions.
  - Compatibility helpers only where they reduce duplication without changing
    user-visible behavior.
- Decisions applied: DAQ-1, DAQ-8, DAQ-9.
- Examples or docs covered: unsupported materialization, checksum evidence,
  backend capability admission summary, redacted diagnostic.
- Out of scope:
  - Artifact materialization execution.
  - Backend handler payload methods.
  - Bundle materialization behavior.
  - Preflight probe execution.
  - Authority import, offline import, retry policy, cleanup, or broad module
    reshuffling.
- Dependencies: landed Stage 15 records and exchange summaries.

### Tasks

- Create the `loom.operations` public module/package without root
  `loom.__init__` export.
- Define final names for the value records and status/severity enums in the
  phase execution plan before implementation.
- Add strict `to_dict`/`from_dict` behavior, plain-data validation, redaction
  helpers, and unsupported/not-implemented constructors.
- Add projection helpers that consumers can use without importing each other.
- Adopt the shared vocabulary in one or more existing result/diagnostic paths
  only where it is behavior-neutral and import direction is clean.
- Add package/import-boundary tests proving `loom.operations` does not import
  `loom.runs`, `loom.diagnostics`, `loom.pipeline`, CLI modules, plugin
  discovery, authority modules, or optional SDKs.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom tests/contracts tests/package` | Target shared records, compatibility projections, and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: shared records round trip strictly, reject unknown fields,
  and preserve redacted plain-data detail.
- Design-decision evidence: `loom.operations` remains value-object-only and
  does not own subsystem protocols.
- Future-roadmap compatibility evidence: records can represent materialization,
  transfer, preflight, retry-readiness, and cleanup-relevant evidence without
  encoding provider-specific fields.
- Interface, adapter, or protocol reuse evidence: adopted projections remove
  duplicated local status/diagnostic logic without changing user behavior.
- Documentation evidence: docstrings or developer docs explain the module
  scope and stop conditions.
- Domain-neutrality evidence: examples use generic adapters and checks, not
  domain artifacts.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: one `loom_phase_refiner` pass available
  because the phase creates public API surface
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: implementation-plan quality gate has passed; a
  scope-complete Phase 1 execution plan is required before product
  implementation
- Merge record: pending

### Risks And Stop Conditions

- Risks: public API overreach, import cycles, behavior changes hidden inside a
  refactor.
- Stop conditions: the phase needs to move authority import, run exchange,
  diagnostics, or materialization protocols into `loom.operations`; the shared
  module needs optional SDKs or plugin discovery; compatibility projections
  change public behavior.
- Assumptions: existing local result objects may keep wrapper names if removing
  them would broaden the phase.

### Completion Summary

- Implementation: complete. Added `loom.operations` shared value records, redacted plain-data details, unsupported/not-implemented constructors, strict serialization tests, contract tests, and import-boundary tests.
- Validation: `make validate-pr` passed; `make test-summary` passed with package, unit, contract, integration, e2e, and config-extra suites green.
- PR: [#166](https://github.com/samcantrill/loom/pull/166) opened against `develop` and verified with `gh pr view 166 --json baseRefName,headRefName,state,url`.
- Merge: merged into `develop` on 2026-05-15 as squash commit `9bbd194acb5fa6d18268312c8a3deba030aae208`; target verified with `gh pr view 166 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` before merge, CI check `checks` succeeded, and the branch was kept because Phase 2 had stacked work.
- Follow-up: rebase Phase 2 from `codex/shared-operation-evidence-contracts` onto updated `develop` and retarget its PR to `develop`.

## Phase 2: Local Materialization Records And Copy Semantics

Status: merged
Slug: `local-materialization-copy-records`
Branch: `codex/local-materialization-copy-records`
Worktree: `/home/samcantrill/work/loom-worktrees/local-materialization-copy-records`
PR: [#167](https://github.com/samcantrill/loom/pull/167)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase creates store-owned public
payload operation records

### Scope

- Goal: add Stage 16 artifact materialization request/result records and
  copy-only local materialization behavior over landed Stage 15 artifact
  summaries using Phase 1 operation/evidence primitives.
- Files/modules owned:
  - `src/loom/pipeline/stores/` materialization module(s)
  - `src/loom/pipeline/stores/__init__.py` public store exports
  - local artifact/store tests
  - contract tests for materialization result schemas
- Behavior implemented:
  - Request/result records for local materialization with source, target,
    policy, checksum, staging, derived location, diagnostics, and operation
    evidence.
  - Copy-only local execution with safe path handling and checksum
    verification when requested or available.
  - Explicit policy handles for hardlink, symlink, reflink, move,
    cache-promote, and future policies that return unsupported/not implemented
    without copying unless copy was selected.
  - Derived `ArtifactLocationSummary` or materialized-ref projection for local
    materialized/staging facts.
- Decisions applied: DAQ-2, DAQ-4, DAQ-5, DSR-3, DSR-6.
- Examples or docs covered: local file copy; checksum success and mismatch;
  unsupported non-copy policy.
- Out of scope:
  - Fake remote backend payload movement.
  - Real backend adapters.
  - Bundle/preflight integration.
  - Retry policy, cleanup, retention, or authority lifecycle mutation.
- Dependencies: Phase 1 shared operation/evidence contracts.

### Tasks

- Define materialization request/result records and final policy/status names.
- Implement local copy helper with safe target handling and clear overwrite or
  collision policy.
- Add checksum evidence helpers that keep byte checksums distinct from
  fingerprints.
- Add derived materialized/staging projection helpers without mutating
  authority lifecycle truth.
- Add unsupported results for non-copy policies and tests proving no silent
  copy fallback.
- Export public store names through `loom.pipeline.stores` only where useful.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/stores tests/contracts tests/package` | Target store records, local copy behavior, unsupported policies, and import boundaries | yes |
| `uv run pytest tests/integration/pipeline/test_artifact_store_split.py tests/integration/pipeline/test_materialization_read_models.py` | Check local artifact-store and materialization read-model compatibility where relevant | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: local copy succeeds, checksum mismatch fails clearly, and
  unsupported policies do not copy.
- Design-decision evidence: artifacts remain metadata-only and store modules
  own materialization policy.
- Future-roadmap compatibility evidence: derived materialized/staging records
  are cleanup-ready but not authoritative artifact truth.
- Interface, adapter, or protocol reuse evidence: results use Phase 1 shared
  operation/evidence records.
- Documentation evidence: public docstrings clarify copy-only semantics and
  future policy handles.
- Domain-neutrality evidence: tests use generic files and artifact refs.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: one `loom_phase_refiner` pass available
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phase 1 merged or valid as stack predecessor
- Merge record: pending

### Risks And Stop Conditions

- Risks: unsafe path handling, treating derived materialized paths as
  authoritative truth, over-designing future policies.
- Stop conditions: copy behavior needs authority lifecycle mutation; non-copy
  policy behavior is required for correctness; implementation needs remote
  backend behavior.
- Assumptions: copy is the only implemented local policy in Stage 16.

### Completion Summary

- Implementation: complete. Added store-owned artifact materialization request/result records, copy-only local materialization, checksum evidence, derived location/materialized-ref projections, unsupported non-copy policy results, and public store exports.
- Validation: `make validate-pr` passed; `make test-summary` passed with package, unit, contract, integration, e2e, and config-extra suites green.
- PR: [#167](https://github.com/samcantrill/loom/pull/167) opened against `develop` and verified with `gh pr view 167 --json baseRefName,headRefName,state,url`.
- Merge: merged into `develop` on 2026-05-15 as squash commit `ddb2a326b27e055c7d1f5c544f90d1b00a9a9464`; target verified with `gh pr view 167 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` before merge, CI check `checks` succeeded, and the branch was kept because Phase 3 had stacked work.
- Follow-up: rebase Phase 3 from `codex/local-materialization-copy-records` onto updated `develop` and target its PR to `develop`.

## Phase 3: Backend Handler Materialization And Fake Remote Operations

Status: merged
Slug: `fake-backend-payload-operations`
Branch: `codex/fake-backend-payload-operations`
Worktree: `/home/samcantrill/work/loom-worktrees/fake-backend-payload-operations`
PR: [#168](https://github.com/samcantrill/loom/pull/168)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase extends backend protocol
behavior and fake conformance coverage

### Scope

- Goal: extend store-owned backend contracts from Stage 15 metadata/check/
  lookup into explicit payload operations proved by fake backends.
- Files/modules owned:
  - `src/loom/pipeline/stores/artifact_backends.py`
  - Stage 16 materialization module(s) under `src/loom/pipeline/stores/`
  - fake backend test support
  - backend contract/unit tests
- Behavior implemented:
  - Handler/capability admission for publish, materialize, upload/download
    style behavior, and checksum verification where supported by the fake.
  - Structured results for supported, unsupported, unknown, failed, checksum
    mismatch, unsafe staging, missing credential-like configuration, and
    redacted backend diagnostics.
  - Fake object-store-style behavior and fake tracking-system-style
    indirection behavior using the same generic result shapes.
  - Staging lifecycle evidence for successful and failed operations.
- Decisions applied: DAQ-2, DAQ-3, DAQ-5, DSR-3, DSR-7.
- Examples or docs covered: read-only object-store fake; writable
  object-store fake; tracking-system indirection fake; unsupported
  materialization.
- Out of scope:
  - Real backend SDKs or optional plugin adapters.
  - Bundle/export/import integration.
  - CLI command surface.
  - Retry, credential lifecycle, deletion, retention, and cleanup.
- Dependencies: Phases 1 and 2.

### Tasks

- Decide whether to extend Stage 15 `ArtifactStoreBackendHandler` directly or
  add a payload-operation companion protocol under stores; record the choice
  in the phase execution plan.
- Map payload operations to landed Stage 15 capability records without
  provider-specific method names in public core records.
- Implement fake backend handlers and fixtures for the required personalities.
- Add checksum and staging evidence paths for success and failure.
- Add redaction tests proving configs, URIs, and exceptions do not leak
  credentials.
- Add contract tests proving unsupported and unknown capabilities fail closed.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/stores tests/contracts tests/package` | Target backend handler/capability/materialization contracts and import boundaries | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: fake backends cover success, unsupported, unknown,
  failure, missing credential-like state, and checksum mismatch.
- Design-decision evidence: no real backend or provider SDK is introduced.
- Future-roadmap compatibility evidence: results carry enough status/evidence
  for Stage 19 retry policy and Stage 20 cleanup policy without implementing
  those policies.
- Interface, adapter, or protocol reuse evidence: both fake personalities use
  the same handler/result shape.
- Documentation evidence: adapter-author docstrings or docs explain payload
  operation semantics and no-backend status.
- Domain-neutrality evidence: fake behavior is generic object/tracking shape,
  not domain-specific experiment data.

### Phase Workflow State

- Phase execution plan: complete in `docs/roadmap/stage-16/phases/fake-backend-payload-operations.md`
- Planning/refinement budget: expanded path; draft and refine used
- Implementation/refinement budget: not needed; targeted validation and the full PR gate passed without implementation blockers
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 and 2 merged; Phase 3 replayed onto updated `develop`
- Merge record: pending

### Risks And Stop Conditions

- Risks: overfitting to a fake provider, protocol churn, accidentally loading
  plugin/optional backend code.
- Stop conditions: a real backend becomes necessary to answer the protocol
  design; fake object-store and tracking-system behavior cannot share the same
  result shape; payload operations require provider-specific public fields.
- Assumptions: no real backend is implemented in Stage 16.

### Completion Summary

- Implementation: complete. Added payload operation records/protocols, public store exports, and fake object-store/tracking-system payload operation coverage.
- Validation: `make validate-pr` passed; `make test-summary` passed with package, unit, contract, integration, e2e, and config-extra suites green.
- PR: [#168](https://github.com/samcantrill/loom/pull/168) opened against `develop` and verified with `gh pr view 168 --json baseRefName,headRefName,state,url`.
- Merge: merged into `develop` on 2026-05-15 as squash commit `325f024677481b98009bf8880445a433297b977f`; target verified with `gh pr view 168 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` before merge, CI check `checks` succeeded, and the branch was kept because Phase 4 had stacked work.
- Follow-up: rebase Phase 4 from `codex/fake-backend-payload-operations` onto updated `develop` and target its PR to `develop`.

## Phase 4: Bundle, Import, Catalog, And Preflight Integration

Status: merged
Slug: `bundle-preflight-materialization`
Branch: `codex/bundle-preflight-materialization`
Worktree: `/home/samcantrill/work/loom-worktrees/bundle-preflight-materialization`
PR: [#169](https://github.com/samcantrill/loom/pull/169)
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase changes user-visible run
exchange, diagnostics, and possible CLI/API behavior

### Scope

- Goal: wire explicit materialization into bundle export/import and preflight
  while preserving metadata-only defaults. Run catalog summaries remain
  unchanged unless the phase execution plan explicitly opts into catalog
  projection changes with additional ownership and tests.
- Files/modules owned:
  - `src/loom/runs/models.py`
  - `src/loom/runs/bundles.py`
  - `src/loom/runs/imports.py`
  - `src/loom/runs/artifact_metadata.py`
  - conditional catalog ownership, only if the phase execution plan opts into
    catalog projection changes: `src/loom/runs/_scan.py`,
    `src/loom/runs/_extract.py`, run catalog contract tests, and affected
    run catalog integration tests
  - `src/loom/diagnostics/models.py`
  - `src/loom/diagnostics/preflight.py`
  - `src/loom/cli/runs.py` only for narrow frequent bundle workflows if the
    API contract is stable and useful
  - run exchange, bundle, diagnostics, CLI/API contract tests
- Behavior implemented:
  - Bundle export/import options for explicit materialization of external or
    remote payloads through fake/store handlers.
  - Metadata-only export/import remains default and does not require backend
    credentials or payload reads.
  - Bundle inspect reports materialization evidence and unsupported paths
    without extraction.
  - Catalog scan/list behavior remains metadata-only and unchanged by default.
    If catalog summaries are changed, the phase must preserve credential-free
    metadata-only catalog behavior and add catalog-specific validation.
  - Preflight adds selected materialization readiness checks and optional
    expensive probes without changing cheap defaults.
  - Narrow CLI is limited to existing bundle/run command families if included;
    no provider-specific or broad materialization CLI is added.
- Decisions applied: DAQ-6, DAQ-7, FR-5, FR-7, FR-8.
- Examples or docs covered: metadata-only bundle; explicit fake-backend
  materialized bundle; unsupported materialization on import; preflight
  readiness with and without expensive probes.
- Out of scope:
  - Real backend SDKs.
  - Credential lifecycle management.
  - Retrying failed transfers.
  - Authority merge/fork or live controller migration.
  - Provider-specific bundle schemas.
- Dependencies: Phases 1 through 3.

### Tasks

- Recheck landed Stage 15 run exchange helpers and choose extension-field
  projection or a narrow schema revision. Prefer projection unless ambiguity
  is concrete and recorded.
- Add run bundle options/results for explicit materialization using Stage 16
  operation evidence.
- Preserve metadata-only import/export behavior and existing bundle
  compatibility.
- Record in the phase execution plan whether run catalog projection is
  unchanged or explicitly changed. If changed, add catalog modules to ownership
  and catalog tests to validation before implementation begins.
- Add preflight request selectors for materialization readiness and expensive
  probes.
- Add no-network default assertions and stable check-ID tests.
- Decide in the phase execution plan whether existing `loom runs export`,
  `loom runs import`, and `loom runs inspect` should expose narrow flags for
  explicit materialization. If not, keep CLI out of scope and test API-level
  handles instead.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/runs tests/unit/loom/diagnostics tests/contracts/test_run_exchange_contract.py tests/contracts/test_run_bundle_export_contract.py tests/contracts/test_run_bundle_import_contract.py tests/contracts/test_cli_runs_contract.py` | Target exchange, bundle, diagnostics, and any included CLI behavior | yes |
| `uv run pytest tests/contracts/test_run_catalog_contract.py tests/integration/pipeline/test_run_catalog_*.py` | Required catalog coverage if the phase execution plan opts into catalog summary changes; otherwise the plan must record catalog unchanged | conditional |
| `uv run pytest tests/integration/pipeline/test_run_bundle_export_inspect.py tests/integration/pipeline/test_run_bundle_import.py tests/integration/diagnostics/test_cli_preflight.py` | Exercise integration paths while preserving metadata-only defaults | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: metadata-only export/import and inspect do not move
  payloads; explicit fake materialization moves supported payloads and reports
  unsupported refs.
- Design-decision evidence: bundle schema remains generic and provider-neutral;
  any schema revision is narrow and justified.
- Future-roadmap compatibility evidence: operation evidence is usable by
  future migration, reliability, and cleanup work without adding live
  controller migration semantics.
- Interface, adapter, or protocol reuse evidence: runs and diagnostics consume
  public operation/store contracts and do not own transfer protocols.
- Documentation evidence: docs or CLI help distinguish metadata preservation
  from explicit materialization.
- Domain-neutrality evidence: bundle tests use generic fake refs.

### Phase Workflow State

- Phase execution plan: complete in `docs/roadmap/stage-16/phases/bundle-preflight-materialization.md`
- Planning/refinement budget: expanded path; draft/refine used in the phase artifact
- Implementation/refinement budget: not needed; targeted validation and the full PR gate passed without implementation blockers
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 through 3 merged; Phase 4 replayed onto updated `develop`
- Merge record: pending

### Risks And Stop Conditions

- Risks: implicit downloads, provider-specific schema, noisy CLI surface,
  expensive preflight by default.
- Stop conditions: materialization requires credentials or network in default
  bundle/preflight paths; landed exchange records cannot preserve generic
  operation evidence without a schema decision; CLI scope expands beyond
  frequent bundle workflows.
- Assumptions: existing Stage 12/15 metadata-only bundle behavior remains
  compatible.

### Completion Summary

- Implementation: complete. Added explicit bundle export materialization through supplied payload handlers, preserved metadata-only defaults, projected materialization evidence through bundle extensions, and added cheap artifact backend materialization readiness preflight.
- Validation: targeted Phase 4 tests passed with 131 passed and 2 skipped; `make validate-pr` passed; `make test-summary` passed with package, unit, contract, integration, e2e, and config-extra suites green.
- PR: [#169](https://github.com/samcantrill/loom/pull/169) opened against `develop` and verified with `gh pr view 169 --json baseRefName,headRefName,state,url,statusCheckRollup,mergeable`; GitHub CI `checks` was in progress at verification time.
- Merge: merged into `develop` on 2026-05-15 as squash commit `de06b07b73d05e624c83490e04091b7810190ea0`; target verified with `gh pr view 169 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup` before merge, CI check `checks` succeeded, and the branch was kept because Phase 5 had stacked work.
- Follow-up: rebase Phase 5 from `codex/bundle-preflight-materialization` onto updated `develop` and target its PR to `develop`.

## Phase 5: No-Backend Finalization And User-Facing Handles

Status: in_progress
Slug: `no-backend-user-facing-handles`
Branch: `codex/no-backend-user-facing-handles`
Worktree: `/home/samcantrill/work/loom-worktrees/no-backend-user-facing-handles`
PR: pending
Base branch: `develop`
Target branch: `develop`
Workflow path: expanded path because this phase hardens public API, docs,
examples, packaging, and final validation

### Scope

- Goal: finalize the Stage 16 no-real-backend decision, docs/examples,
  package/import hardening, unsupported handles, and narrow user-facing
  affordances after the core materialization behavior is in place.
- Files/modules owned:
  - docs under `docs/features/` and `docs/roadmap/stage-16/`
  - examples or test fixtures if present
  - package/import-boundary tests
  - public API/CLI tests for unsupported handles
- Behavior implemented:
  - Stable unsupported/not-implemented handles for unselected real backend
    paths and unsupported local policies.
  - Documentation and examples showing bundle/export/import materialization,
    metadata-only defaults, copy-only local behavior, and fake backend
    semantics.
  - Package tests proving no optional SDKs are imported or required.
  - Any narrow CLI/help polish selected by Phase 4, without adding broad
    provider commands.
- Decisions applied: DAQ-3, FR-6, FR-8.
- Examples or docs covered: no-backend default; future backend adapter
  extension point; unsupported real backend; explicit copy local
  materialization; fake bundle workflow.
- Out of scope:
  - Adding a real backend.
  - Optional dependency extras for provider SDKs.
  - Broad provider CLI.
  - Reliability or cleanup policy.
- Dependencies: Phases 1 through 4.

### Tasks

- Update feature docs for materialization, remote stores, artifacts, preflight,
  run catalog, and testing where Stage 16 behavior changes user expectations.
- Add or update examples demonstrating explicit materialization and
  metadata-only defaults.
- Harden package/import-boundary tests for no optional backend dependencies.
- Add public API tests for unsupported real-backend and future-policy handles.
- Run final validation commands and record suite evidence for PR preparation.

### Validation

| Command/check | Purpose | Required before phase complete |
| --- | --- | --- |
| `uv run pytest tests/package tests/contracts tests/unit/loom tests/integration` | Broad package, contract, unit, and integration coverage before final PR | yes |
| `make validate-pr` | Full PR gate for phase | yes |
| `make test-summary` | Suite-level PR evidence | yes |

### Acceptance Evidence

- Behavior evidence: unsupported real-backend and future-policy handles are
  stable and redacted.
- Design-decision evidence: implementation explicitly records no real backend
  family in Stage 16.
- Future-roadmap compatibility evidence: docs identify revisit triggers for a
  future real backend, retry policy, and cleanup policy.
- Interface, adapter, or protocol reuse evidence: public docs describe how
  future adapters use existing store/operation contracts.
- Documentation evidence: feature docs and examples are updated.
- Domain-neutrality evidence: examples remain generic and do not assume an ML
  or cloud provider domain.

### Phase Workflow State

- Phase execution plan: pending
- Planning/refinement budget: expanded path; draft and refine expected
- Implementation/refinement budget: one `loom_phase_refiner` pass available
- PR review budget: one automated review pass available
- Blocker-resolution budget: unused
- Pre-submit blocker gate: Phases 1 through 4 merged or valid as stack
  predecessors
- Merge record: pending

### Risks And Stop Conditions

- Risks: docs implying real backend support, optional dependencies sneaking
  into default imports, CLI surface becoming too broad.
- Stop conditions: a concrete backend becomes required; examples require a
  real service; package tests reveal optional dependency imports.
- Assumptions: no real backend is selected before phase implementation begins.

### Completion Summary

- Implementation: pending
- Validation: pending
- PR: pending
- Merge: pending
- Follow-up: pending

## Cross-Phase Validation

- Full relevant test command: phase PRs must run targeted phase tests plus
  `make validate-pr`; final PR preparation for every phase must run
  `make test-summary` for suite-level evidence.
- Docs/template checks: `git diff --check` for documentation diffs, plus
  affected docs/examples tests where present.
- Domain-neutrality checks: no provider-specific public schema, no domain
  artifact names, no optional SDK imports, no network default.
- Example/demo checks: fake-backend-only examples; local copy temp-directory
  examples; metadata-only bundle examples.
- Manual review focus: import direction, public API scope, unsupported/fail
  closed behavior, redaction, metadata-only defaults, bundle schema
  compatibility, and derived/non-authoritative staging semantics.

## Plan Quality Gate

- Status: passed
- Required reviewer: `loom_plan_reviewer`
- Required sequence: one review pass, one bounded refinement pass if blocking
  or material findings are reported, and one confirmation review.
- Review scope: planning readiness, maintainability, extensibility, future
  compatibility, conflicting design choices, accepted technical debt, test
  strategy, reviewability, and no unresolved `blocked` or `needs discussion`
  decisions.
- Stop condition: do not create Phase 1 execution plans or begin product
  implementation while blocking plan-review findings remain unresolved.
- Review pass: complete. The reviewer reported no blocking findings and two
  refinement items.
- Refinement pass: complete. Phase 4 now explicitly records catalog scope and
  conditional catalog tests, and every phase now requires `make test-summary`
  for PR evidence.
- Confirmation review: complete. No remaining blocking findings.

## Implementation Plan Review

| Finding | Severity | Resolution | Status |
| --- | --- | --- | --- |
| Phase 4 catalog coverage was underspecified | concern | Phase 4 now declares catalog behavior unchanged unless the phase execution plan explicitly opts into catalog projection changes; if opted in, catalog modules and catalog contract/integration tests are required | resolved |
| `make test-summary` was not explicit for every phase PR | note | Cross-phase validation and every phase validation table now require `make test-summary` for suite-level PR evidence | resolved |
| Plan quality gate confirmation review | blocker | Confirmation review completed with no remaining blocking findings | resolved |

Gate result:

- Status: passed
- Review evidence: `loom_plan_reviewer` completed review with no blocking
  findings; bounded refinement applied to catalog scope and test-summary
  evidence requirements; confirmation review found no remaining blocking
  findings
- Accepted risks:
  - No real backend proof in Stage 16.
  - New `loom.operations` public path must stay narrow.
  - Bundle evidence projection may need a narrow schema adaptation.
- Revisit triggers:
  - Concrete backend requirement appears before phase implementation.
  - Fake backend personalities cannot share the same handler/result shape.
  - `loom.operations` needs subsystem imports or lifecycle protocols.
  - Existing exchange fields cannot represent operation evidence clearly.

## Final Approval

- Approval status: approved for Phase 1 execution planning
- Approved scope: five-phase Stage 16 plan as recorded above
- Accepted risks: no real backend proof in Stage 16, narrow public
  `loom.operations` import path, and possible narrow bundle operation-evidence
  schema adaptation
- Deferred items: real backend implementation, non-copy local policies,
  retry/timeout policy, credential lifecycle, cleanup/retention/GC, live
  controller migration, global cache/reuse behavior
