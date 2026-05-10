# Phase 2 Execution Plan: Run/Stage Store Contracts

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 2 - Generic RunStore/StageStore Interfaces And Conformance Harness
- Status: in_progress
- Branch: `codex/run-stage-store-contracts`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/run-stage-store-contracts`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 2: Run and Stage Store Contracts`
- Draft pass: complete on 2026-05-10
- Refine pass: not planned; this execution plan is scope-complete and the
  expanded-path design choices are bounded below.
- Phase implementation refinement budget: unused
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## Scope

This phase defines the public authority contract that later runtime,
diagnostic, service, and HPC phases must reuse. It does not migrate all runtime
entrypoints, implement the service backend, or remove transitional SQLite
authority.

The implementation will:

- Reclaim the root public `loom.pipeline.stores.RunStore` export for
  authority-backed run lifecycle semantics.
- Add a scoped `StageStore` authority protocol under `RunStore`.
- Rename the current path-shaped aggregate protocol to an explicit
  transitional local/runtime name so existing call sites can keep compiling
  without satisfying the new authority protocol by accident.
- Add `AuthorityConfig`, `AuthorityReference`, backend kind, deployment
  profile, redaction, and safe plain-data serialization records.
- Add one factory path, `create_run_store(...)`, that returns the public
  authority `RunStore` and can wrap existing per-run authority stores for this
  phase.
- Add a required-capability admission vocabulary and structured diagnostics
  shared by future runner, CLI, SLURM, worker, diagnostics, and sweep callers.
- Add a backend-parametric conformance harness that validates run lifecycle,
  scoped stage lifecycle, leases, fencing, submitted operations, output
  commits, snapshots, stale transitions, and recovery against the public
  `RunStore`/`StageStore` surface.

## Out Of Scope

- Broad runtime caller migration beyond import renames needed to keep legacy
  call sites explicitly transitional.
- Service/database backend implementation.
- Artifact/materialization interface split beyond preserving current names.
- SQLite authority removal.
- CLI/environment plumbing.

## Design Impact

Very high. This phase establishes the names and contracts every later phase
depends on. The main compatibility risk is that the current `RunStore` name is
used as a local runtime aggregate in many modules. To keep the diff reviewable,
the public package export changes now while old call sites import the explicit
transitional aggregate.

## Future Compatibility

The public factory/configuration and admission records must be broad enough to
represent co-located, managed-service, allocation-scoped, direct-database, and
deferred-finalization profiles without making those backends available before
their phases. Unsupported backend kinds fail closed at factory or admission
time with structured diagnostics.

## Alternatives Rejected

- Leaving `RunStore` as the path-shaped aggregate. That would preserve the
  local lifecycle escape hatch and force later phases to define a second public
  authority name.
- Encoding the conformance contract only in `SQLitePerRunAuthorityStore`.
  Future service and direct database backends need reusable contract coverage.
- Moving all runtime call sites in this phase. That belongs to Phases 4-6 and
  would obscure the API review.

## Debt Introduced

- The transitional local/runtime aggregate remains for existing implementation
  modules until later migration phases remove it.
- The factory can wrap existing per-run authority implementations and
  transitional SQLite authority, but managed service, allocation-scoped,
  direct database, and deferred-finalization behavior remain unimplemented
  until later phases.

## Acceptance Criteria

- Public `RunStore` manages run admission/opening, run lifecycle, run-level
  leases, submitted operations, snapshots, recovery, cleanup candidates, and
  access to scoped `StageStore` handles.
- `StageStore` is scoped by `(run_uri, stage_name)` and manages stage
  lifecycle, attempt allocation, leases, submitted-operation access, fenced
  output commits, snapshots, recovery, and cleanup candidates.
- The old path-shaped local aggregate has an explicit transitional name and is
  not the root public authority `RunStore` export.
- `LocalRunStore` does not satisfy the public authority `RunStore` protocol.
- `create_run_store(...)` is the only public factory path introduced in this
  phase.
- Capability diagnostics name the selected backend/profile, missing
  capability, requested feature, and code.
- The conformance harness can run against any backend adapter that returns the
  public authority `RunStore` surface.

## Suite Obligations

- Package: public exports and import-boundary tests for authority config,
  factory, `RunStore`, and `StageStore`; package import must not import
  `sqlite3`.
- Unit: configuration serialization/redaction and capability admission
  diagnostics.
- Contract: public authority conformance harness for in-memory and
  transitional SQLite-backed adapters, plus compatibility tests for legacy
  path-shaped stores.
- Integration: minimal factory smoke test through the transitional SQLite
  backend.
- E2E: not required for this interface-only phase.
- Opt-in: not required.

## Stop Conditions

- A runtime migration is required to make the public authority interface
  type-check beyond explicit transitional import renames.
- The public factory cannot stay import-light without importing the concrete
  SQLite implementation at package import time.
- Admission semantics require scheduler-specific decisions that belong to
  Phase 5 or Phase 8.
