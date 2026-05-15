# Phase 2 Execution Plan: Artifact-Store Backend Contracts

## Metadata

- Status: implementation complete; PR preparation in progress
- Feature focus: External Artifact Interface
- PR title: `External Artifact Interface - Phase 2: Artifact-Store Backend Contracts`
- Branch: `codex/artifact-store-backend-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/artifact-store-backend-contracts`
- Phase execution plan path:
  `docs/roadmap/stage-15/phases/artifact-store-backend-contracts.md`
- Full plan: `docs/roadmap/stage-15/implementation-plan.md`
- Source phase: Phase 2, `artifact-store-backend-contracts`
- Stack predecessor: none; Phase 1 is merged
- Base branch: `develop` at `0e0af7c97039d7bc5df398c0897b24b7bf7bd65a`
- Target branch: `develop`
- Merge eligibility: root PR may merge to `develop` after implementation,
  validation, PR preparation, automated review, and GitHub merge checks.
- Workflow path: expanded path because this phase creates public extension
  contracts.
- Successor dependency notes: Phase 3 should branch from this phase branch only
  if this phase PR cannot merge; otherwise branch from updated `develop`.
- Plan quality gate: passed in the implementation plan; Phase 1 has merged and
  recorded validation/merge metadata.
- Plan quality gate loop budget: used by the implementation plan gate.
- Draft pass: complete in this artifact.
- Refine pass: complete in this artifact; field boundaries, plugin-loader
  boundary, and stop conditions were tightened for public contract work.
- Setup limitations: sandboxed broad pytest hit local authority-service socket
  restrictions; required validation was rerun outside the sandbox.
- Blockers: none.

## Objective

Add store-owned, dependency-light artifact-store backend contracts: descriptor
and factory records, handler protocol, registry, operation capabilities,
structured diagnostics/results, fake contract fixtures, and an explicit
supplied-registry plugin adapter.

## Full-Plan Context

Phase 1 added plain artifact records. Phase 2 defines how backend packages
describe and register handlers without changing runner wiring, generic plugin
readiness, preflight, catalog/bundle preservation, run exchange, or payload
movement. Phases 3-6 consume these contracts for immutable semantics,
diagnostics, exchange metadata, and docs/examples.

## Stack Context

- Root or stacked phase: root phase after Phase 1 merge.
- Current predecessor branch or PR: none.
- Why this base branch is correct: Phase 1 merged to `develop`, and no
  unmerged Stage 15 predecessor remains.
- Retarget/rebase plan after predecessor merge: not applicable.
- Branch cleanup constraints: delete after merge if no successor depends on it.

## Source Phase Summary

- Goal: define descriptor/factory, handler, registry, capability, fake-backend,
  operation-result, and supplied-registry plugin adapter contracts.
- Required scope: new focused store modules, store exports, optional lazy plugin
  adapter, unit/contract/package tests.
- Required checkpoints: duplicate/missing backend behavior, incompatible
  contract version, unsupported operation result, fake tracking/object-store
  descriptors, plugin adapter registering into a supplied registry.
- Acceptance criteria: programmatic registration works without plugins; generic
  Stage 14 readiness remains listing-only; raw `ArtifactStore` objects,
  local-root factories, plugin-owned registries, and universal plugin objects
  are rejected.

## Current Source And Harness Findings

- `loom.pipeline.stores` already has authority capability records under
  `capabilities.py`; Phase 2 must not conflate those with artifact operation
  capabilities.
- `loom.plugins.entrypoints` exposes generic metadata/list/load primitives and
  the `loom.artifact_store_backends` group constant. No artifact-store backend
  loader exists today.
- `LOADABLE_PLUGIN_GROUPS` intentionally remains recipes/codecs only. This phase
  may add a specialized lazy adapter export, but must not make generic
  `plugins.load` or readiness imply backend run-readiness.
- Package import-boundary tests already protect stores and plugins from pulling
  heavy layers by default.

## In-Scope Work

- Add `loom.pipeline.stores.artifact_backends` or equivalent focused module
  with strict backend version, descriptor, factory, handler, registry,
  capability, diagnostic, and unsupported-result records.
- Export public store contract names from `loom.pipeline.stores`.
- Add `loom.plugins.artifact_backends` with
  `load_artifact_store_backend_entry_points(...)`, using Stage 14 generic
  loading and registering only into a caller-supplied
  `ArtifactStoreBackendRegistry`.
- Add fake tracking-style and object-store-style descriptors/handlers in tests
  only.
- Add unit, contract, and package tests for registry behavior, plugin adapter
  boundary, exports, and import safety.

## Out-of-Scope Work

- Real MLflow, DVC, HTTP, S3, GCS, Azure, cloud, or tracking adapters.
- Backend SDK imports, network/credential probes, upload/download, deletion,
  materialization, or runner artifact-store replacement.
- Generic Stage 14 readiness changes that claim artifact-store backend
  availability or run-readiness.
- Preflight check IDs, catalog/bundle preservation, Stage 12 exchange updates,
  or immutable lookup behavior beyond structured unsupported results.

## Assumptions

- The contract version starts at `1`.
- Backend kind normalization is lowercase kebab-case-ish ASCII with underscores
  normalized to hyphens.
- Handler methods in Phase 2 are metadata/check/lookup oriented and return
  structured unsupported results for payload operations.
- Plugin targets are descriptors, factories, or zero-argument callables that
  return descriptors/factories; any object outside that shape is rejected.

## Scope Contract

- Public contract version helpers must accept only current major version `1`.
- `ArtifactStoreBackendDescriptor` records: `kind`, `display_name`,
  `contract_version`, `api_version`, `supported_uri_schemes`, `details`, and a
  `factory` object not included in serialization.
- `ArtifactStoreBackendFactory` protocol/factory object must validate/redact
  config, report capabilities, and create a handler from a redacted
  `ArtifactStoreRef` plus optional run context.
- `ArtifactStoreBackendHandler` protocol must expose backend kind, store ref,
  capabilities, metadata validation, cheap checks, lookup, and unsupported
  operation helpers. It must not require SDK clients or payload movement.
- `ArtifactStoreCapabilities` uses operation-specific support records with
  `supported`, `unsupported`, and `unknown` states.
- `ArtifactStoreBackendRegistry` is keyed by normalized backend kind and raises
  deterministic duplicate/missing/version errors.
- Plugin adapter loading is explicit, supplied-registry-based, and lazy from
  `loom.plugins`; no import of `loom.plugins` from store modules.

## Design Impact

- Maintainability: store-owned contracts avoid plugin discovery owning backend
  semantics.
- Extensibility: optional backend packages can register descriptors without
  coupling core to service SDKs.
- Domain neutrality: fake tests use tracking/object-store shapes without
  service-specific core fields.
- Source-tree boundaries: stores may import `loom.artifacts`; plugins may
  import stores for the specialized adapter; stores must not import plugins.

## Future Compatibility

Stage 16 can add materialization behind these handlers; Stage 19 can add
retry/timeout records; Stage 20 can consume delete/retention capabilities. Phase
2 must leave unsupported/unknown states explicit so later behavior can fail
closed.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Raw `ArtifactStore` plugin targets | They expose runtime store instances rather than backend descriptors/config/capabilities. |
| Current local-root factory as plugin contract | It cannot express backend config, capability, version, or redaction policy. |
| Plugin-owned registries | Store contracts own backend semantics; plugins only load selected entry points. |
| Universal plugin object protocol | Too broad for deterministic validation and adapter author guidance. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Specialized plugin loader exists while generic readiness remains listing-only | Prevents false run-readiness while enabling explicit adapter loading | Docs can distinguish descriptor-load success from configured backend readiness |
| Fake handlers define first contract pressure tests | Needed before real adapters exist | First real optional backend exposes missing generic fields |

## Reviewability

- Expected PR size and shape: one focused store contract module, one lazy plugin
  adapter module, exports, and tests.
- Files and areas to inspect: store backend contracts, plugin adapter,
  package/import-boundary tests, contract tests.
- Scope-control checks: no runner wiring, no real service imports, no generic
  readiness change, no preflight/catalog/bundle/exchange code.

## Implementation Steps

1. Add artifact backend contract records/protocols/registry under stores.
2. Add capability support-state records and unsupported operation results.
3. Add store exports and package tests.
4. Add explicit plugin adapter and plugin tests without changing generic
   readiness.
5. Add contract tests using fake tracking/object-store descriptors.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_plugins_api.py`, `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: exports and import boundaries.

### Unit Suite

- Status: required.
- Expected paths: `tests/unit/loom/pipeline/stores`,
  `tests/unit/loom/plugins`.
- Required assertions or deferral reason: registry, capabilities, adapter.

### Contract Suite

- Status: required.
- Expected paths: new `tests/contracts/test_artifact_store_backend_contract.py`
  plus plugin future-group contract updates as needed.
- Required assertions or deferral reason: fake backend descriptor/handler,
  unsupported results, duplicate/missing/version behavior.

### Integration Suite

- Status: deferred for new focused coverage.
- Expected paths: none.
- Required assertions or deferral reason: no runner/preflight integration in
  Phase 2.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: no CLI workflow changes.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: no service-backed or network suites.

## Risks

- Capability records may overlap authority style. Keep names artifact-store
  specific and extract later only if shared behavior becomes substantial.
- Plugin adapter could imply run-readiness. Tests/docs must keep generic
  readiness listing-only and distinguish descriptor registration from backend
  availability.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/stores tests/unit/loom/plugins tests/contracts/test_artifact_store_backend_contract.py tests/package/test_pipeline_store_api.py tests/package/test_plugins_api.py tests/package/test_import_boundaries.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For Implementation

- Safe implementation slices: store contracts, tests, plugin adapter, exports.
- Tests to run with each slice: start with the new contract/unit tests, then
  package import tests.
- Decisions not to revisit: no real backends, no generic plugin readiness
  promotion, no preflight/catalog/bundle/run-exchange work, no payload ops.
- Stop conditions: contract needs plugin discovery in store modules, optional
  dependency, runner wiring, or public API outside the phase plan.

## Refinement And Review Budget Status

- Phase execution plan draft: complete.
- Phase execution plan refine: complete.
- Phase implementation refinement: not needed; targeted and full validation
  passed after a focused export-fixture test update.
- PR review: unused.
- Blocker resolution: 0/3 used.

## Completion Notes

- Draft plan: complete.
- Final phase execution plan: complete.
- Implementation summary: added `loom.pipeline.stores.artifact_backends` with
  descriptor/factory/handler protocols, operation-specific capability records,
  structured diagnostics/results, contract version helpers, normalized
  backend-kind registry behavior, and public store exports. Added lazy
  `loom.plugins.load_artifact_store_backend_entry_points(...)` that uses Stage
  14 entry-point loading into a caller-supplied registry while leaving generic
  artifact-store backend readiness listing-only.
- Implementation validation:
  - Targeted focused command passed: 76 passed.
  - Broad Phase 2 command passed outside the sandbox:
    `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores tests/unit/loom/plugins tests/contracts tests/package`
    with 522 passed and 3 skipped.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed: Ruff passed, Pyright
    passed with 0 errors, default harness passed with 1634 passed / 26 skipped
    / 18 deselected, config-extra passed with 440 passed / 1671 deselected,
    and build succeeded.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed and wrote
    `build/test-summary.md`: overall 2102 passed / 18 skipped / 1687
    deselected.
- Refinement summary: no `loom_phase_refiner` pass was used; local fix updated
  the existing store export fixture after broad validation found the new public
  names missing from that assertion.
- Blocker-resolution summary: none.
- PR preparation: in progress; PR body drafted in
  `docs/roadmap/stage-15/phases/artifact-store-backend-contracts-pr-body.md`.
- Stack maintenance: Phase 1 merged; no predecessor.
- Remaining blockers: none.
