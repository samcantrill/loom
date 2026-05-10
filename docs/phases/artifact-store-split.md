# Phase 3 Execution Plan: Artifact Store Split

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 3 - RunArtifactStore And StageArtifactStore Split
- Status: approved
- Branch: `codex/artifact-store-split`
- Worktree: `/home/samcantrill/work/loom-worktrees/artifact-store-split`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/111
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 3: Artifact Store Split`
- Draft pass: complete on 2026-05-10
- Refine pass: not planned; the phase is bounded to protocol and local-wrapper
  introduction.
- Phase implementation refinement budget: unused
- Phase PR review budget: used locally on 2026-05-10; no blocking findings.
- Blocker-resolution budget: 0/3 used

## PR Preparation Notes

- PR #111 opened on 2026-05-10 against `develop` from
  `codex/artifact-store-split`.
- Verified immediately after creation: base `develop`, head
  `codex/artifact-store-split`, state `OPEN`, CI `checks` in progress.
- Automated review confirmed the PR targets `develop`, stays within the Phase
  3 artifact/materialization split, avoids runtime caller migration, and keeps
  lifecycle status/attempt/lease/submitted-operation/output-commit/snapshot
  surfaces out of the new wrappers.

## Scope

This phase introduces artifact/materialization-only run and stage surfaces while
leaving broad runtime caller migration for later phases.

The implementation will:

- Add `RunArtifactStore` and `StageArtifactStore` protocols that expose local
  path, config/provenance/log, worker handoff, generated file, and payload
  materialization responsibilities without lifecycle methods.
- Add local implementations that wrap the existing local run layout but expose
  only the artifact/materialization protocols.
- Keep the existing `ArtifactStore` payload API intact.
- Export the new protocols and local wrappers from `loom.pipeline.stores`
  without importing heavy optional modules.
- Add package, unit, and contract tests proving the artifact surfaces exclude
  run/stage status, attempts, leases, submitted operations, output commits,
  snapshots, recovery, and behavior summaries.
- Update the run-store feature doc with the artifact/materialization boundary.

## Out Of Scope

- Migrating `PipelineRunner`, CLI, worker, SLURM, diagnostics, or catalog
  call sites to the new wrappers.
- Changing authority lifecycle behavior.
- Implementing remote artifact payload stores.
- Removing `LocalRunStore` or its transitional local runtime behavior.

## Design Impact

High. This phase creates the explicit file/materialization boundary later
runtime and read-model phases will use to stop importing local lifecycle
behavior through `LocalRunStore`.

## Future Compatibility

The protocols are intentionally plain and local-path oriented for now, but the
method split keeps room for future remote artifact materialization by separating
payload access from lifecycle authority. Marker methods prevent the broad
`LocalRunStore` implementation from accidentally satisfying these new safe
wrapper protocols structurally.

## Alternatives Rejected

- Reusing `LocalRunStorePaths` as the artifact boundary. It still includes run
  identity helpers and is paired with the legacy runtime aggregate in many
  call sites.
- Migrating all call sites now. That belongs to Phases 4-6 and would obscure
  the protocol review.
- Adding lifecycle read helpers for old local status files. That would preserve
  local files as behavior truth.

## Debt Introduced

- Existing runtime modules still use `LegacyRunStore` until later phases
  migrate execution and read paths.
- The local artifact wrappers delegate to `LocalRunStore` internally to avoid
  duplicating local layout code. The public wrapper protocols hide lifecycle
  methods, and later phases can move the implementation behind standalone
  modules if needed.

## Acceptance Criteria

- Artifact/materialization protocols expose no status, attempt, lease,
  submitted-operation, output-commit, snapshot, recovery, or behavior-summary
  methods.
- `LocalRunStore` does not satisfy the new safe artifact protocols.
- Local wrappers cover current config/provenance/log/generated-file, worker
  handoff, stage workspace, and artifact-root path needs.
- Existing payload `ArtifactStore` behavior remains unchanged.
- Docs describe artifact/materialization stores as non-authoritative.

## Suite Obligations

- Package: public export and import-boundary tests for the new protocols and
  local wrappers.
- Unit: local wrapper delegation, path safety, and absence of lifecycle methods.
- Contract: artifact/materialization protocol tests.
- Integration: local materialization wrapper round trip.
- E2E: not required.
- Opt-in: not required.

## Implementation Summary

- Added `RunArtifactStore` and `StageArtifactStore` protocols to
  `src/loom/pipeline/stores/artifact_store.py`.
- Added `LocalRunArtifactStore` and `LocalStageArtifactStore` wrappers that
  delegate to the existing local layout while exposing only
  artifact/materialization methods.
- Kept payload `ArtifactStore` and `LocalArtifactStore` behavior unchanged.
- Exported the new protocols and wrappers from `loom.pipeline.stores`.
- Added package, unit, contract, and integration tests proving wrapper
  behavior and absence of lifecycle methods.
- Updated `docs/features/run-store.md` to describe
  `RunArtifactStore`/`StageArtifactStore` as non-authoritative
  materialization surfaces.

## Validation Evidence

- Focused checks before full validation:
  - `uv run ruff check ...` passed for changed Phase 3 source and tests.
  - `uv run pytest tests/package/test_pipeline_store_api.py
    tests/unit/loom/pipeline/stores/test_store_errors.py
    tests/unit/loom/pipeline/stores/test_local_artifacts.py
    tests/contracts/test_store_contract.py
    tests/integration/pipeline/test_artifact_store_split.py` passed with
    26 passed.
  - `uv run --extra config pyright` passed with 0 errors.
- `make validate-pr` passed Ruff, Pyright, default tests, config-extra tests,
  and build.
- `make test-summary` wrote `build/test-summary.md` with:
  - package: 57 passed, 1 skipped.
  - unit: 836 passed, 1 skipped.
  - contract: 108 passed, 2 skipped.
  - integration: 90 passed, 8 skipped, 10 deselected.
  - e2e: 39 passed, 1 deselected.
  - config-extra: 420 passed, 1133 deselected.

## Stop Conditions

- A runtime migration is required to keep existing behavior working.
- Artifact wrappers need to expose status, attempts, submitted operations, or
  snapshots to satisfy current tests.
- Remote artifact payload semantics are required to define the local protocol.
