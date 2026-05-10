# Phase 2 Execution Plan: Run/Stage Store Contracts

## Metadata

- Implementation plan:
  `docs/implementation-plans/implementation-plan-v9-post.md`
- Phase: 2 - Generic RunStore/StageStore Interfaces And Conformance Harness
- Status: pr_open
- Branch: `codex/run-stage-store-contracts`
- Worktree:
  `/home/samcantrill/work/loom-worktrees/run-stage-store-contracts`
- Stack predecessor: none
- Base branch: `develop`
- PR target branch: `develop`
- PR: https://github.com/samcantrill/loom/pull/110
- PR feature focus: `Authority Runtime Unification`
- Intended PR title:
  `Authority Runtime Unification - Phase 2: Run and Stage Store Contracts`
- Draft pass: complete on 2026-05-10
- Refine pass: not planned; this execution plan is scope-complete and the
  expanded-path design choices are bounded below.
- Phase implementation refinement budget: used locally on 2026-05-10 to update
  the mirrored `loom.pipeline.stores.__all__` unit expectation after
  `make validate-pr` exposed the missing Phase 2 exports.
- Phase PR review budget: unused
- Blocker-resolution budget: 0/3 used

## PR Preparation Notes

- PR #110 opened on 2026-05-10 against `develop` from
  `codex/run-stage-store-contracts`.
- Verified immediately after creation: base `develop`, head
  `codex/run-stage-store-contracts`, state `OPEN`, CI `checks` in progress.

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

## Implementation Summary

- Added public authority `RunStore` and scoped `StageStore` protocols that sit
  above the existing per-run authority contract.
- Renamed the current path-shaped aggregate to `LegacyRunStore` and updated
  existing runtime call sites to import that transitional name explicitly.
- Added `AuthorityConfig`, `AuthorityReference`, backend-kind/deployment
  profile records, redaction helpers, `create_run_store(...)`, and
  capability-admission records.
- Added a public `RunStore` adapter over `PerRunAuthorityStore`, with support
  for explicit in-memory/test stores and transitional SQLite authority.
- Expanded backend capability declarations with run admission, lease TTL,
  fencing, monotonic revisions, transaction/clock semantics, topology, service,
  shared-filesystem, and deferred-finalization vocabulary.
- Added reusable public authority conformance checks plus package, unit,
  contract, and integration coverage.
- Documented the v9-post public naming transition in
  `docs/features/run-store.md`.

## Validation Evidence

- Focused checks before full validation:
  - `uv run ruff check ...` passed for changed Phase 2 source and tests.
  - `uv run pytest tests/package/test_pipeline_store_api.py
    tests/unit/loom/pipeline/stores/test_authority_config_admission.py
    tests/contracts/test_store_contract.py
    tests/contracts/test_run_store_authority_contract.py
    tests/contracts/test_authority_store_contract.py
    tests/integration/pipeline/test_authority_factory.py` passed with
    31 passed.
  - `uv run --extra config pyright` passed with 0 errors.
- First `make validate-pr` run passed Ruff, Pyright, and 1099 default tests
  before failing one mirrored export expectation in
  `tests/unit/loom/pipeline/stores/test_store_errors.py`.
- Final `make validate-pr` passed Ruff, Pyright, default tests, config-extra
  tests, and build.
- `make test-summary` wrote `build/test-summary.md` with:
  - package: 57 passed, 1 skipped.
  - unit: 834 passed, 1 skipped.
  - contract: 107 passed, 2 skipped.
  - integration: 89 passed, 8 skipped, 10 deselected.
  - e2e: 39 passed, 1 deselected.
  - config-extra: 420 passed, 1129 deselected.

## Stop Conditions

- A runtime migration is required to make the public authority interface
  type-check beyond explicit transitional import renames.
- The public factory cannot stay import-light without importing the concrete
  SQLite implementation at package import time.
- Admission semantics require scheduler-specific decisions that belong to
  Phase 5 or Phase 8.
