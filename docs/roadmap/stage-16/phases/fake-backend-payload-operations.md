# Phase 3 Execution Plan: Backend Handler Materialization And Fake Remote Operations

## Metadata

- Status: implementation complete - ready for PR
- Feature focus: Artifact Payload Materialization
- PR title: `Artifact Payload Materialization - Phase 3: Fake Backend Payload Operations`
- Branch: `codex/fake-backend-payload-operations`
- Worktree: `/home/samcantrill/work/loom-worktrees/fake-backend-payload-operations`
- Phase execution plan path: `docs/roadmap/stage-16/phases/fake-backend-payload-operations.md`
- Full plan: `docs/roadmap/stage-16/implementation-plan.md`
- Source phase: `Phase 3: Backend Handler Materialization And Fake Remote Operations`
- Stack predecessor: none; Phase 2 merged into `develop` before PR preparation
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible after phase validation passes, automated review passes, CI passes, and PR target verification confirms `develop`
- Workflow path: expanded path
- Successor dependency notes: Phase 4 should branch from this branch if Phase 3 remains unmerged
- Plan quality gate: passed in the implementation plan on 2026-05-15
- Plan quality gate loop budget: consumed and passed; do not rerun unless the implementation plan changes
- Draft pass: complete in this artifact
- Refine pass: complete in this artifact
- Setup limitations: none; Phase 3 was replayed onto `develop` after Phase 2 squash merge
- Blockers: none

## Objective

Extend store-owned backend contracts from Stage 15 metadata lookup into explicit payload-operation records and a fake-backend-tested companion handler surface. This phase proves object-store-style and tracking-system-style payload operations without adding real provider adapters or optional SDKs.

## Full-Plan Context

Phase 1 added shared operation/evidence records, and Phase 2 added copy-only local materialization records. Phase 3 adds backend payload request/result records and a companion protocol for explicit payload operations. Phase 4 will connect these operations to bundle/preflight flows. This phase must not add bundle/export/import behavior, preflight probes, CLI flags, real backends, credential lifecycle, retries, cleanup, or provider-specific schemas.

## Stack Context

- Root or stacked phase: root PR after Phase 2 merge
- Current predecessor branch or PR: none; Phase 2 PR [#167](https://github.com/samcantrill/loom/pull/167) merged into `develop`
- Why this base branch is correct: Phase 3 depends on Phase 1 `loom.operations` and Phase 2 materialization records, both now merged on `develop`
- Retarget/rebase plan after predecessor merge: completed on 2026-05-15 with `git rebase --onto origin/develop codex/local-materialization-copy-records codex/fake-backend-payload-operations`
- Branch cleanup constraints: Phase 3 no longer depends on the Phase 2 branch

## Source Phase Summary

- Goal: extend store-owned backend contracts from metadata/check/lookup into explicit payload operations proved by fake backends.
- Required scope: backend operation enum additions, payload request/result records, companion payload handler protocol, fake object-store and tracking-system contract tests, checksum/staging evidence, unsupported/unknown/failure behavior, and redaction tests.
- Required checkpoints: no real backend SDKs, no provider-specific public fields, both fake personalities use the same request/result shape, and unsupported capabilities fail closed.
- Acceptance criteria: fake backends cover success, unsupported, unknown, failure, missing credential-like state, checksum mismatch, read-only object-store, writable object-store, and tracking-system indirection paths.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/artifact_backends.py` owns backend descriptors, capability records, handlers, registries, and unsupported results; `src/loom/pipeline/stores/artifact_materialization.py` owns local materialization records; existing Stage 15 contract tests use fake backend factories inside `tests/contracts/test_artifact_store_backend_contract.py`.
- Existing tests or harness behavior: backend contracts and diagnostics are covered in `tests/contracts/test_artifact_store_backend_contract.py`, `tests/contracts/test_backend_diagnostics_contract.py`, and `tests/unit/loom/pipeline/stores/test_artifact_backends.py`.
- Import-boundary or dependency constraints: backend contracts may import `loom.artifacts`, `loom.operations`, and plain serialization helpers. They must not import runs, diagnostics, CLI, plugin discovery, optional SDKs, or provider clients.

## In-Scope Work

- Add `UPLOAD` and `DOWNLOAD` backend operation enum values while preserving existing operation values.
- Add backend payload operation request/result value records in `artifact_backends.py`.
- Add a companion `ArtifactStoreBackendPayloadHandler` protocol with one generic `payload_operation(request)` method rather than adding payload methods to the Stage 15 metadata handler protocol.
- Add unsupported/not-implemented payload operation helper constructors that use `OperationResult`.
- Add fake backend contract coverage for object-store-style upload/download/materialize/verify/publish and tracking-system-style indirection using the same request/result shape.
- Add capability admission tests for supported, unsupported, unknown, failed, checksum mismatch, unsafe/missing target, and missing credential-like cases.

## Out-of-Scope Work

- Real S3/GCS/Azure/MLflow/DVC/W&B/HTTP adapters or optional SDK dependencies.
- Bundle/export/import integration, preflight integration, run catalog changes, or CLI flags.
- Retry/timeout policy, credential lifecycle, deletion, retention, cleanup, or global cache/reuse.
- Provider-specific public request/result fields.

## Assumptions

- Fake backend handlers can live in contract tests; production core only needs the neutral records/protocols and helpers.
- A companion protocol minimizes breakage for existing metadata-only handlers while still letting payload-capable handlers opt in.
- Staging lifecycle evidence can be represented in `OperationEvidenceRecord.details` and result details until Phase 4 decides how to project it through bundles/preflight.

## Scope Contract

`ArtifactStorePayloadOperationRequest` contains `operation`, optional `artifact`, `source_uri`, `target_uri`, optional `checksum`, and `details`. `operation` must be one of the payload-relevant `ArtifactStoreBackendOperation` values: `PUBLISH`, `MATERIALIZE`, `UPLOAD`, `DOWNLOAD`, or `VERIFY_CHECKSUM`.

`ArtifactStorePayloadOperationResult` contains the request, an `OperationResult`, optional `ArtifactLocationSummary`, optional `bytes_processed`, and plain details. `OperationResult` is the canonical status/evidence carrier.

`ArtifactStoreBackendPayloadHandler` is a runtime-checkable companion protocol:

- it exposes descriptor, store_ref, capabilities, and `payload_operation(request)`;
- it does not replace `ArtifactStoreBackendHandler`;
- metadata-only handlers can remain valid without implementing it.

## Design Impact

- Maintainability: payload operations become explicit backend contracts without expanding the metadata lookup handler.
- Extensibility: real adapters can implement the companion protocol later and return the same generic result records used by fake handlers.
- Domain neutrality: fake scenarios use object/tracking naming only and no ML/cloud SDK concepts.
- Source-tree boundaries: stores own payload operation contracts; runs and diagnostics remain consumers in later phases.

## Future Compatibility

- Phase 4 can call payload-capable fake handlers from bundle/preflight selectors.
- Stage 19 can inspect `OperationResult` diagnostics for retry/timeout policy.
- Stage 20 can use operation evidence/details for cleanup decisions without adding cleanup behavior here.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add payload methods directly to `ArtifactStoreBackendHandler` | Would force all metadata-only handlers to implement future payload behavior and break Stage 15 compatibility. |
| Add provider-specific upload/download request fields | Overfits fake contracts to one real backend family before a backend is selected. |
| Implement a first real backend adapter | Stage 16 explicitly skips real backends until a concrete downstream need appears. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Fake handlers live in tests | Proves contract shape without committing production fake service behavior or SDK dependencies | Phase 4 needs reusable fake handlers outside tests. |
| Companion protocol is generic one-method dispatch | Avoids provider-specific public methods and keeps operations enumerated | A real adapter needs richer typed request surfaces. |
| Staging evidence is details-based | Keeps Phase 3 independent from bundle/preflight schema decisions | Phase 4 needs persisted or projected staging schema. |

## Reviewability

- Expected PR size and shape: backend contract records/protocols, public exports, focused backend contract/unit tests, and phase docs.
- Files and areas to inspect: `artifact_backends.py`, `stores/__init__.py`, backend contract tests, backend unit tests, package export tests.
- Scope-control checks: no real backend imports, no bundle/preflight/CLI changes, no provider-specific schema, no retries/cleanup.

## Implementation Steps

1. Extend backend operations and add payload request/result records plus helper constructors.
2. Add `ArtifactStoreBackendPayloadHandler` as a companion protocol and export names through `loom.pipeline.stores`.
3. Add fake object-store-style and tracking-system-style handlers in contract tests using the same request/result shape.
4. Cover success, unsupported, unknown, failure, missing credential-like state, checksum mismatch, redaction, and read-only/writable behavior.
5. Run targeted validation, then final PR validation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: public store exports include the new names and no optional SDK imports appear.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_artifact_backends.py`
- Required assertions or deferral reason: payload records serialize strictly, reject invalid operations, and helper constructors produce structured operation results.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_artifact_store_payload_operations_contract.py`
- Required assertions or deferral reason: object-store-style and tracking-system-style fake handlers share the same protocol/result shape and fail closed.

### Integration Suite

- Status: deferred
- Expected paths: none required
- Required assertions or deferral reason: Phase 3 adds backend contracts and fake contract tests only; bundle/preflight integration is Phase 4.

### E2E Suite

- Status: deferred
- Expected paths: none required
- Required assertions or deferral reason: no CLI/user workflow changes are in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no real backend or optional provider dependency is introduced.

## Risks

- Adding operations to the enum can affect existing capability tests if expected export/order lists are missed.
- A companion protocol could become too generic if it starts carrying lifecycle, retry, or provider-specific semantics.
- Fake-only validation may miss real-provider needs; tests must cover enough shape diversity to make that debt explicit.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/stores/test_artifact_backends.py tests/contracts/test_artifact_store_payload_operations_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
uv run pytest tests/contracts/test_artifact_store_backend_contract.py tests/contracts/test_backend_diagnostics_contract.py tests/contracts/test_artifact_materialization_contract.py
git diff --check
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: records/protocols first, fake contract tests second, export/package tests third.
- Tests to run with each slice: backend unit tests after records, contract tests after fake handlers, package tests after exports.
- Decisions the executor must not revisit: companion protocol rather than mutating `ArtifactStoreBackendHandler`; no real backend; no provider-specific request fields; no bundle/preflight/CLI behavior.
- Conditions that require stopping for the manager: fake object-store and tracking-system scenarios cannot share one result shape; provider-specific fields are needed; optional SDKs become necessary; payload operations need bundle/preflight code to be meaningful.

## Refinement And Review Budget Status

- Planning draft pass: used
- Planning refine pass: used
- Phase implementation refinement: not needed; targeted validation and the full PR gate passed without implementation blockers
- PR review: unused; one automated review pass remains available
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: refined and ready for implementation
- Implementation summary: complete. Added `UPLOAD` and `DOWNLOAD` backend operations, strict payload request/result records, a runtime-checkable companion payload handler protocol, public store exports, and fake object-store/tracking-system contract coverage.
- Implementation validation: targeted Phase 3 suite passed with 73 tests; adjacent backend/materialization compatibility suite passed with 8 tests; `git diff --check`, Ruff changed-file checks, and Pyright changed-file checks passed. `make validate-pr` passed with Ruff, Pyright, default suite `1691 passed, 26 skipped, 18 deselected`, config-extra suite `440 passed, 1728 deselected`, and build. `make test-summary` passed with package `97 passed, 1 skipped`, unit `1184 passed, 7 skipped, 1 deselected`, contract `239 passed, 2 skipped`, integration `156 passed, 8 skipped, 13 deselected`, e2e `43 passed, 2 deselected`, and config-extra `440 passed, 1728 deselected`.
- Refinement summary: no separate implementation refinement pass was needed because targeted validation and full PR validation passed.
- Blocker-resolution summary: none
- PR preparation: body prepared in `docs/roadmap/stage-16/phases/fake-backend-payload-operations-pr-body.md`
- Stack maintenance: replayed onto `develop` after Phase 2 merged; PR should target `develop`
- Remaining blockers: none
