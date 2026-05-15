# Phase 2 Execution Plan: Local Materialization Records And Copy Semantics

## Metadata

- Status: refined phase execution plan - ready for implementation
- Feature focus: Artifact Payload Materialization
- PR title: `Artifact Payload Materialization - Phase 2: Local Materialization Copy Records`
- Branch: `codex/local-materialization-copy-records`
- Worktree: `/home/samcantrill/work/loom-worktrees/local-materialization-copy-records`
- Phase execution plan path: `docs/roadmap/stage-16/phases/local-materialization-copy-records.md`
- Full plan: `docs/roadmap/stage-16/implementation-plan.md`
- Source phase: `Phase 2: Local Materialization Records And Copy Semantics`
- Stack predecessor: none; Phase 1 merged before PR preparation
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: eligible only after phase validation, automated review, GitHub CI, and PR target verification against `develop`
- Workflow path: expanded path
- Successor dependency notes: Phase 3 should branch from this branch if Phase 2 remains unmerged
- Plan quality gate: passed in the implementation plan on 2026-05-15
- Plan quality gate loop budget: consumed and passed; do not rerun unless the implementation plan changes
- Draft pass: complete in this artifact
- Refine pass: complete in this artifact
- Setup limitations: initial implementation started stacked on Phase 1, then branch was replayed onto `origin/develop` after Phase 1 merged
- Blockers: none

## Objective

Add store-owned Stage 16 records and local copy behavior for explicit artifact payload materialization. The phase must use Phase 1 operation/evidence records, keep `loom.artifacts` metadata-only, and fail closed for every non-copy local policy.

## Full-Plan Context

Phase 1 added the shared operation/evidence vocabulary. This phase uses that vocabulary under `loom.pipeline.stores` to model and execute local copy materialization only. Phase 3 will extend backend fake payload operations, Phase 4 will connect materialization to bundles/preflight, and Phase 5 will harden user-facing docs and no-backend handles. This phase must not add fake remote backend behavior, bundle/export/import options, preflight probes, CLI flags, real adapters, retry policy, cleanup, or authority lifecycle mutation.

## Stack Context

- Root or stacked phase: root phase after Phase 1 merge
- Current predecessor branch or PR: none; Phase 1 PR [#166](https://github.com/samcantrill/loom/pull/166) merged into `develop`
- Why this base branch is correct: Phase 2 depends on `loom.operations`, and the branch was replayed onto `origin/develop` after Phase 1 merged
- Retarget/rebase plan after predecessor merge: completed before PR preparation
- Branch cleanup constraints: no successor branch depends on Phase 1 after this replay

## Source Phase Summary

- Goal: add Stage 16 materialization request/result records and copy-only local behavior over landed Stage 15 artifact summaries using Phase 1 operation/evidence primitives.
- Required scope: store-owned materialization module(s), public store exports, local copy helper, checksum evidence, derived materialized/staging projections, unsupported future-policy handles, and focused tests.
- Required checkpoints: artifacts remain metadata-only; non-copy policies never silently copy; results use `loom.operations`; derived locations are not authority truth.
- Acceptance criteria: local copy succeeds, checksum mismatch fails clearly, unsupported policies do not copy, and package/import boundaries remain clean.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/local_artifacts.py` implements local file artifact save/register/load/verify; `src/loom/pipeline/stores/materialization_read_models.py` already exports a read-model `LocalMaterializationRequest`, so this phase must avoid that name; `src/loom/pipeline/stores/read_models.py` owns `MaterializedRef`.
- Existing tests or harness behavior: local artifact behavior is covered in `tests/unit/loom/pipeline/stores/test_local_artifacts.py`; materialization read-model compatibility is covered by unit and integration tests; public exports are checked in `tests/package/test_pipeline_store_api.py`.
- Import-boundary or dependency constraints: new store code may import `loom.artifacts`, `loom.operations`, filesystem helpers, and serialization helpers. It must not import `loom.runs`, `loom.diagnostics`, CLI, plugin discovery, optional SDKs, or authority service/server modules.

## In-Scope Work

- Add a new store-owned module, `src/loom/pipeline/stores/artifact_materialization.py`.
- Define final public names:
  - `ArtifactMaterializationError`
  - `LocalMaterializationPolicy`
  - `ArtifactMaterializationRequest`
  - `ArtifactMaterializationResult`
  - `materialize_artifact_locally`
  - `artifact_materialization_location`
  - `artifact_materialized_ref`
- Add strict serialization for request/result records, with `ArtifactRef`, target path, policy, overwrite, checksum verification, operation result, derived location, materialized ref, bytes copied, and details.
- Implement copy-only local file materialization with safe target handling and atomic-ish parent directory creation.
- Return structured unsupported/not-implemented `OperationResult` values for hardlink, symlink, reflink, move, cache-promote, and future policies.
- Add checksum evidence that compares byte checksums and keeps checksum distinct from fingerprint.
- Project derived `ArtifactLocationSummary` and `MaterializedRef` values for successful local materialization.
- Export public store names through `loom.pipeline.stores` and update package tests.

## Out-of-Scope Work

- Directory copy materialization, non-copy local policies, cache promotion, deletion, cleanup, retention, or garbage collection.
- Remote/fake backend publish/materialize/upload/download/verify operations.
- Bundle export/import/inspect materialization, preflight materialization probes, catalog changes, or CLI flags.
- Authority lifecycle mutation or authoritative artifact truth changes.

## Assumptions

- Local copy materialization applies to regular files only in Phase 2.
- Target collision policy is explicit: `overwrite=False` fails closed when the target exists; `overwrite=True` replaces the target file.
- `verify_checksum=True` verifies against `ArtifactRef.checksum` when present and records unproven evidence when no checksum is available.
- `ArtifactMaterializationRequest.target_path` serializes as a filesystem path string; later bundle phases can decide whether to wrap this in URI options.

## Scope Contract

`ArtifactMaterializationRequest` is the caller-owned request record. It contains `artifact`, `target_path`, `policy`, `overwrite`, `verify_checksum`, and `details`. `policy` defaults to `LocalMaterializationPolicy.COPY`. The request does not mutate the artifact and does not imply bundle/preflight behavior.

`ArtifactMaterializationResult` is the store-owned operation result. It contains `request`, `operation`, `source_uri`, `target_uri`, `location`, `materialized_ref`, `bytes_copied`, and `details`. `operation` is an `OperationResult` and is the canonical status/diagnostic/evidence carrier.

Failure behavior:

- Missing source, unsupported source URI, unsafe target path, existing target without overwrite, directory source, checksum mismatch, and copy I/O failures return `OperationStatus.FAILED` or `OperationStatus.BLOCKED` with diagnostics. They do not silently succeed.
- Non-copy policies return unsupported or not-implemented results and must not create, replace, or modify the target.
- Successful copy returns `OperationStatus.SUCCEEDED`, checksum evidence where available, a derived `ArtifactLocationSummary(kind=MATERIALIZED, authority=derived)`, and a `MaterializedRef(kind=ARTIFACT_PAYLOAD)`.

## Design Impact

- Maintainability: materialization policy lives in one store-owned module rather than in artifacts, runs, diagnostics, or CLI.
- Extensibility: request/result records reserve policy and evidence space for fake backends, future non-copy policies, retry policy, and cleanup.
- Domain neutrality: tests use generic file payloads and artifact refs.
- Source-tree boundaries: `loom.pipeline.stores` consumes `loom.operations`; no higher-level consumer code is imported.

## Future Compatibility

- Phase 3 can reuse the request/result and evidence shape for fake backend payload operations.
- Phase 4 can pass these results through bundle/import/preflight projections without moving operation ownership into runs or diagnostics.
- Stage 19 can layer retry/timeout policy over `OperationResult`.
- Stage 20 can identify derived materialized refs for cleanup without treating them as authoritative artifact truth.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Add materialization behavior to `loom.artifacts` | Artifacts must remain metadata-only value objects. |
| Implement hardlink or symlink as an optimization now | Stage 16 explicitly selected copy-only local behavior for portability and safety. |
| Silently fall back to copy for future policies | The plan requires fail-closed unsupported results when a caller asks for a non-copy policy. |
| Mutate authority/read-model state during copy | Materialized/staging facts are derived and non-authoritative in this phase. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| File-only local copy materialization | Keeps Phase 2 small and avoids directory semantics, partial copies, and cleanup policy | Bundle or backend phases need directory payload materialization. |
| Future policies exist as enum values before implementation | Keeps request/result contracts stable for later local policy additions | A later stage selects hardlink, symlink, reflink, move, or cache promotion. |
| Target overwrite is a simple bool | Adequate for local deterministic tests and copy-only semantics | Future staging or cache promotion needs richer collision policy. |

## Reviewability

- Expected PR size and shape: one new store module, store public exports, focused unit/contract/package tests, and phase plan/PR body docs.
- Files and areas to inspect: `artifact_materialization.py`, `stores/__init__.py`, local materialization tests, contract result-schema tests, package export/import-boundary tests.
- Scope-control checks: no remote backend operations, no bundle/preflight/CLI behavior, no artifact metadata mutation, no non-copy behavior, no optional SDK imports.

## Implementation Steps

1. Add `artifact_materialization.py` with policy enum, request/result records, strict serialization, projection helpers, and unsupported-policy helpers.
2. Implement `materialize_artifact_locally` for copy-only regular-file materialization with source/target validation, overwrite handling, byte copy, checksum evidence, and derived location/ref projection.
3. Export the public names through `loom.pipeline.stores` and update package API/import-boundary tests.
4. Add unit and contract tests for copy success, missing source, checksum mismatch, overwrite behavior, unsupported non-copy policies, strict result serialization, and no silent copy fallback.
5. Run targeted validation, then final PR validation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: public store exports include the new names, and importing stores still avoids forbidden runtime/CLI/plugin layers and optional SDKs.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_artifact_materialization.py`, existing local artifact tests as needed
- Required assertions or deferral reason: copy success, checksum evidence, checksum mismatch, missing source, collision/overwrite behavior, and unsupported non-copy policies.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_artifact_materialization_contract.py`
- Required assertions or deferral reason: request/result serialized shapes are strict, plain-data-safe, and use `loom.operations` result/evidence records.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_artifact_store_split.py`, `tests/integration/pipeline/test_materialization_read_models.py`
- Required assertions or deferral reason: existing local artifact-store and materialization read-model behavior remains compatible.

### E2E Suite

- Status: deferred
- Expected paths: none required
- Required assertions or deferral reason: no CLI or user workflow behavior changes are in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no real backend, network, or optional provider dependency behavior is in scope.

## Risks

- Unsafe target handling could copy outside intended caller-selected paths or replace data unexpectedly.
- Directory or non-file sources could create partial materialization semantics if allowed too early.
- Derived materialized refs could be mistaken for authoritative artifact truth if docs/tests do not assert the derived boundary.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py
uv run pytest tests/integration/pipeline/test_artifact_store_split.py tests/integration/pipeline/test_materialization_read_models.py
git diff --check
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: records first, copy helper second, exports/tests third.
- Tests to run with each slice: unit/contract tests after records; local copy tests after helper; package tests after exports.
- Decisions the executor must not revisit: copy-only policy, enum names above, no artifact/root export changes, no directory materialization, no bundle/preflight/CLI behavior, and no authority mutation.
- Conditions that require stopping for the manager: copy behavior requires authority lifecycle mutation; non-copy policy must be implemented to satisfy tests; remote backend behavior is needed; target safety cannot be represented without a broader staging policy.

## Refinement And Review Budget Status

- Planning draft pass: used
- Planning refine pass: used
- Phase implementation refinement: unused; one expanded-path pass remains available if targeted validation fails or review finds a bounded blocker
- PR review: unused; one automated review pass remains available
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: refined and ready for implementation
- Implementation summary: added `artifact_materialization.py` with request/result records, copy-only local materialization, checksum evidence, derived `ArtifactLocationSummary` and `MaterializedRef` projections, and unsupported results for non-copy policies. Exported public store names and added unit/contract/package tests.
- Implementation validation: `uv run pytest tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py` -> `76 passed`; `uv run pytest tests/integration/pipeline/test_artifact_store_split.py tests/integration/pipeline/test_materialization_read_models.py` -> `5 passed`; `uv run pytest tests/unit/loom/pipeline/stores/test_store_errors.py tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py tests/package/test_pipeline_store_api.py` -> `27 passed`; `uv run ruff check src/loom/pipeline/stores/artifact_materialization.py src/loom/pipeline/stores/__init__.py tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py` -> passed; `uv run pyright src/loom/pipeline/stores/artifact_materialization.py tests/unit/loom/pipeline/stores/test_artifact_materialization.py tests/contracts/test_artifact_materialization_contract.py` -> `0 errors`; `git diff --check` -> passed; `make validate-pr` -> passed after updating the existing store export assertion for the new public names.
- Refinement summary: pending
- Blocker-resolution summary: none
- PR preparation: pending
- Stack maintenance: branch replayed from `codex/shared-operation-evidence-contracts` onto `origin/develop` after Phase 1 merged
- Remaining blockers: none
