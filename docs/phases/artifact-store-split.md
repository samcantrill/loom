# Phase 3 Execution Plan: Artifact Store Split

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 3 - RunArtifactStore And StageArtifactStore Split
- Status: in_progress
- Branch: `codex/artifact-store-split`
- Worktree: `/home/samcantrill/work/loom-worktrees/artifact-store-split`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 3: Artifact Store Split`
- Draft pass: complete on 2026-05-10
- Refine pass: not planned; the phase is bounded to protocol and local-wrapper
  introduction.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

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

## Stop Conditions

- A runtime migration is required to keep existing behavior working.
- Artifact wrappers need to expose status, attempts, submitted operations, or
  snapshots to satisfy current tests.
- Remote artifact payload semantics are required to define the local protocol.
