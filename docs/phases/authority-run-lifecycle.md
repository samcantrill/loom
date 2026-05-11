# Phase 5 Execution Plan: Run Lifecycle Repository

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 5: Run Lifecycle Repository`
- Branch: `codex/authority-run-lifecycle`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-run-lifecycle`
- Phase execution plan path: `docs/phases/authority-run-lifecycle.md`
- Full plan: `docs/implementation-plans/implementation-plan-v10.md`
- Source phase: Phase 5 - Run Lifecycle Repository
- Stack predecessor: none; Phase 4 is merged in PR #122 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 6 adds stage, attempt, output, artifact, and stage-lease repository behavior; Phase 7 wires repository behavior to FastAPI mutation routes.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/implementation-plans/implementation-plan-v10.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: none unresolved. Branch and worktree were created from local `develop` at `1c37af5`, after Phase 4 merge metadata was pushed.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Persist run-level authority state in the private service repository: run admission, run status transitions, controller leases, revision/fencing checks, submitted operations, audit events, cleanup candidates, recovery records, and run snapshots without implementing stage lifecycle persistence or HTTP route wiring.

## Full-Plan Context

Phase 4 created the private SQLite repository foundation and compatibility checks. Phase 5 turns that repository into the durable source of truth for run-level lifecycle facts. Phase 6 owns stage-level mutation semantics, and Phase 7 owns FastAPI mutation mapping, so this phase must expose private repository methods and read models only.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 4 merged to `develop` in PR #122
- Why this base branch is correct: the implementation plan records Phase 4 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: persist run lifecycle authority behavior in the private repository.
- Required scope: run admission, run status transitions, controller leases, run snapshots, audit events, cleanup/recovery records, revision facts, valid transition ordering, and stale revision rejection.
- Required checkpoints: repository-level tests for admit/transition/readback, controller leases, stale revision/fencing errors, cleanup/recovery queryability, and privacy boundaries.
- Acceptance criteria: repository tests can drive run lifecycle sequences, controller leases are durable and fenced, revisions reject stale mutation, cleanup/recovery records are durable, and behavior remains below the service API boundary.

## Current Source And Harness Findings

- `src/loom/authority/_repository.py` owns the private SQLite connection, schema version, compatibility checks, and explicit transaction wrapper. Phase 5 should extend this module rather than create public store modules.
- The Phase 4 schema version is `1` and contains only metadata. Adding run lifecycle tables is a durable private schema change, so Phase 5 should bump the private repository schema version and let older metadata-only repositories fail as unsupported older.
- `src/loom/pipeline/stores/sqlite_authority.py` has useful local patterns for revisions, `LeaseRecord`, `AuthoritativeRunSnapshot`, submitted operations, audit events, cleanup candidates, and recovery records. Phase 5 should reuse the value models and transaction style, not copy stage/attempt/output logic.
- `src/loom/pipeline/stores/authority.py` already defines backend-neutral records such as `StatusTransition`; `read_models.py` defines `BackendRevision`, `LeaseRecord`, `CleanupCandidate`, `RecoveryRecord`, and `AuthoritativeRunSnapshot`.
- Existing package import tests ensure importing `loom.authority` does not import `sqlite3`, `loom.authority._repository`, FastAPI, Pydantic, Starlette, or `loom.pipeline`.

## In-Scope Work

- Extend the private repository schema with cross-run tables for revisions, runs, controller leases, submitted operations, cleanup candidates, and audit events.
- Bump the private authority repository schema version and update compatibility tests for older metadata-only repositories.
- Add private run lifecycle methods for run admission, run opening/snapshot, run transitions, controller lease acquire/renew/release/fail, submitted-operation write/read/list, audit append/list, cleanup candidate record/list, and recovery scan/list.
- Enforce status transition preconditions, expected revision checks, duplicate run rejection, stale or foreign fencing token rejection, active controller lease conflicts, and expired controller lease recovery.
- Return existing backend-neutral value records where they fit: `BackendRevision`, `StatusTransition`, `LeaseRecord`, `SubmittedOperationRecord`, `PipelineEventRecord`, `CleanupCandidate`, `RecoveryRecord`, and `AuthoritativeRunSnapshot`.
- Add package, unit, contract, and integration tests for the private run lifecycle surface.

## Out-of-Scope Work

- Stage lifecycle tables, attempts, stage leases, output commits, artifact facts, and materialized refs.
- FastAPI mutation routes, HTTP status mapping, client transport behavior, readiness route repository probing, and supervisor process commands.
- Runtime factory adoption, runner/worker caller migration, workspace coordination, resource admission, registry files, and offline import manifests.
- Public exports from `loom.authority`, `loom.pipeline.stores`, or CLI packages for the private repository.

## Assumptions

- Private repository schema version `2` can represent the first run lifecycle schema. Repositories stamped with version `1` are rejected rather than migrated in this phase.
- Run snapshots may return empty `stages` and `materialized_refs` until Phase 6 adds stage lifecycle data.
- Controller leases use the existing `LeaseRecord` model with `LeaseKind.CONTROLLER`; lease methods take `run_uri` explicitly so no in-memory lease-to-run cache is required.
- Expected revision checks are optional on private methods but must reject when provided and not equal to the current run revision.

## Scope Contract

The repository remains private to `loom.authority._repository`. This phase may import backend-neutral pipeline value records to avoid duplicate models, but those imports must stay behind the private module and must not be reached by `import loom.authority`.

Run lifecycle mutations are optimistic and revisioned. A mutation that receives `expected_revision` must compare both sequence and token with the current run revision and raise a repository error before writing if the value is stale. Status transitions must also compare the caller's `from_status` with the persisted run status. Controller lease mutations must require the correct owner and fencing token, must reject stale or foreign tokens, and must reject expired leases.

The private schema must store enough facts for later protocol mapping: run status, metadata, reason, created/updated revisions, monotonic revision rows, controller lease state, submitted operations, audit event sequence, cleanup candidates, and recovery records. Stage and output details must remain absent.

## Design Impact

- Maintainability: concentrates run-level durable state and mutation checks in one repository module before route code exists.
- Extensibility: revision, lease, cleanup, and recovery tables give later API, supervisor, and import phases stable private facts without making the SQL schema public.
- Domain neutrality: records describe generic Loom run lifecycle facts only.
- Source-tree boundaries: no public package root imports the repository; route and runtime layers remain untouched.

## Future Compatibility

The schema should leave room for Phase 6 stage tables keyed by `run_uri`, future repository diagnostics, and offline import provenance. The phase should avoid a general backend abstraction until the service repository has concrete run and stage behavior.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep schema version `1` and add tables silently | Metadata-only Phase 4 repositories would appear compatible even though required run tables are absent. |
| Reuse `SQLitePerRunAuthorityStore` directly | It stores one DB per run and includes stage/output behavior that belongs to later phases. |
| Add FastAPI route handlers now | Phase 7 owns HTTP mutation mapping. |
| Store only an append-only event log | Phase acceptance requires snapshots and durable queryable lease/cleanup facts. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Private repository API is concrete SQLite-first rather than abstracted | The roadmap chooses a local DB-backed authority first; alternate backends are future work. | Hosted or non-SQLite authority backend is planned. |
| Run snapshots omit stage/output details | Phase 6 owns stage lifecycle and output persistence. | Phase 6 begins stage repository behavior. |
| Older private schema versions are rejected, not migrated | No released service repository exists yet and migrations are outside this phase. | A public release ships a private repository schema that must be upgraded in place. |

## Reviewability

- Expected PR size and shape: moderate extension to `_repository.py` plus focused package, unit, contract, and integration tests.
- Files and areas to inspect: `src/loom/authority/_repository.py`, repository tests under `tests/unit/loom/authority`, `tests/contracts`, `tests/integration/authority`, and package import-boundary tests.
- Scope-control checks: no FastAPI route wiring, no stage lifecycle, no attempt allocation, no output commits, no runtime factory adoption, no public exports, and no direct-database runtime profile.

## Implementation Steps

1. Extend private schema constants/checks with run lifecycle tables and schema version `2`.
2. Add private lifecycle helpers for revisions, JSON serialization, run lookup, expected revision checks, and snapshots.
3. Implement run admission, run transitions, submitted operations, audit events, cleanup candidates, and recovery records.
4. Implement controller lease acquire/renew/release/fail behavior with TTL, fencing, and stale revision checks.
5. Add package, unit, contract, and integration tests for lifecycle semantics, schema compatibility, and privacy.
6. Run targeted validation, then final `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `loom.authority` remains lightweight and does not import the private repository, `sqlite3`, or `loom.pipeline`; repository lifecycle symbols are not exported from the public package root.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_repository.py` and/or `tests/unit/loom/authority/test_repository_run_lifecycle.py`
- Required assertions or deferral reason: schema version bump, older v1 rejection, revision generation, stale expected revision rejection, duplicate run rejection, transition preconditions, submitted-operation serialization, audit event sequencing, cleanup candidate serialization, and controller lease validation.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_repository_contract.py`
- Required assertions or deferral reason: private repository run lifecycle outputs align with backend-neutral protocol/read-model records, and stale revision/fencing conflicts can map to existing protocol rejection categories without importing FastAPI.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_repository.py` and/or `tests/integration/authority/test_repository_run_lifecycle.py`
- Required assertions or deferral reason: file-backed admit/reopen/transition/snapshot sequences, controller lease persistence across handles, expired lease recovery, submitted-operation read/list, audit event durability, cleanup candidate durability, and transaction rollback around lifecycle writes.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI, supervisor process, FastAPI mutation route, runtime caller, or user workflow behavior changes.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no network, scheduler, external service, or long-running process is required.

## Risks

- Accidentally importing the private repository from `loom.authority` would make pipeline models eager and break package boundaries.
- Under-specified stale revision or fencing errors would make later protocol mapping inconsistent.
- Copying stage/output behavior from the per-run SQLite backend would expand into Phase 6.
- Schema version handling could accidentally accept metadata-only repositories as lifecycle-capable.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/authority/_repository.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_repository_run_lifecycle.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/integration/authority/test_repository_run_lifecycle.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority/_repository.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_repository_run_lifecycle.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/integration/authority/test_repository_run_lifecycle.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_repository_run_lifecycle.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/integration/authority/test_repository_run_lifecycle.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: schema/version extension, revision and run admission helpers, run transition/snapshot behavior, controller leases, submitted/audit/cleanup/recovery records, then import-boundary and suite coverage.
- Tests to run with each slice: unit tests after schema/revision/run helpers, contract tests after stale revision/fencing records, integration tests after file-backed lease and recovery behavior, package tests after import-boundary assertions.
- Decisions the executor must not revisit: repository stays private under `loom.authority`, schema version bumps to `2`, stage/output/attempt behavior is deferred, no public exports are added, and no HTTP route mapping is implemented.
- Conditions that require stopping for the manager: need to expose repository symbols publicly, need to change Phase 3 FastAPI route contracts, need to implement stage lifecycle to satisfy run tests, or inability to reject stale revisions/fencing without broader protocol redesign.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-11 by managing agent after
  implementation and validation; no code changes were required
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary: extended the private authority repository to schema
  version 2 with cross-run run lifecycle tables, monotonic repository
  revisions, run admission and transitions, expected-revision checks,
  controller lease acquire/renew/release/fail with fencing and TTL checks,
  submitted operation persistence, audit event persistence, cleanup candidate
  records, recovery records, and run-level recovery scanning. The work stayed
  private to `loom.authority._repository` and did not add route, stage,
  attempt, output, artifact, runtime, or public export behavior.
- Implementation validation: targeted `ruff`, `pyright`, and focused package,
  unit, contract, and integration pytest passed for the repository changes.
  Final `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed, including Ruff,
  Pyright, default pytest with 1227 passed, 18 skipped, 14 deselected,
  config-extra pytest with 420 passed and 1256 deselected, and package build.
  Final `UV_CACHE_DIR=/tmp/uv-cache make test-summary` passed with overall
  1673 passed, 12 skipped, and 1267 deselected.
- Refinement summary: bounded implementation review inspected private import
  boundaries, schema-version behavior, run-only scope, revision/fencing checks,
  controller lease persistence, cleanup/recovery queryability, and suite
  evidence. No scope or correctness blockers were found, and no code changes
  were required after validation.
- Blocker-resolution summary: not needed; 0/3 blocker-resolution passes used.
- PR preparation: PR body prepared in
  `docs/phases/authority-run-lifecycle-pr-body.md`; PR opening pending.
- Stack maintenance: root phase targets `develop`; no successor branch depends
  on `codex/authority-run-lifecycle` yet.
- Remaining blockers: none known.
