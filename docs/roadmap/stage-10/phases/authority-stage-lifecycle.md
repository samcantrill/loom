# Phase 6 Execution Plan: Stage Lifecycle Repository

## Metadata

- Status: refined phase execution plan
- Feature focus: DB-Backed Authority Supervisor And Offline Import
- PR title: `DB-Backed Authority Supervisor And Offline Import - Phase 6: Stage Lifecycle Repository`
- Branch: `codex/authority-stage-lifecycle`
- Worktree: `/home/samcantrill/work/loom-worktrees/authority-stage-lifecycle`
- Phase execution plan path: `docs/roadmap/stage-10/phases/authority-stage-lifecycle.md`
- Full plan: `docs/roadmap/stage-10/implementation-plan.md`
- Source phase: Phase 6 - Stage Lifecycle Repository
- Stack predecessor: none; Phase 5 is merged in PR #123 and recorded in the plan
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root phase, merge-eligible after PR targets `develop` and automated gates pass
- Workflow path: expanded path
- Successor dependency notes: Phase 7 wires repository behavior to FastAPI mutation routes and client protocol mapping; later runtime phases adopt the service boundary.
- Plan quality gate: passed on 2026-05-11 after one refinement pass and confirmation review; evidence is recorded in `docs/roadmap/stage-10/implementation-plan.md`
- Plan quality gate loop budget: consumed; do not reopen unless the v10 implementation plan changes materially
- Draft pass: completed by managing agent on 2026-05-11
- Refine pass: completed by managing agent on 2026-05-11
- Setup limitations: none unresolved. Branch and worktree were created from local `develop` at `ab6ea3c`, after Phase 5 merge metadata was pushed.
- Blockers: none; implementation may begin from this refined phase execution plan.

## Objective

Persist stage-level authority state in the private repository: stage transitions, attempt allocation, attempt terminal-state updates, submitted operations already introduced in Phase 5, stage leases, output commits, artifact facts, stale generation checks, stale lease/fencing checks, and stage-aware run snapshots without wiring HTTP routes or migrating runtime callers.

## Full-Plan Context

Phase 5 made the private repository durable for run lifecycle state and controller leases. Phase 6 adds the stage mutation semantics that later FastAPI routes and runtime callers will depend on. Phase 7 owns protocol/HTTP mapping, so this phase should expose private repository methods and value records only.

## Stack Context

- Root or stacked phase: root phase
- Current predecessor branch or PR: none; Phase 5 merged to `develop` in PR #123
- Why this base branch is correct: the implementation plan records Phase 5 merged, the control checkout was fast-forwarded to `develop`, and no unmerged predecessor branch exists
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete the phase branch and worktree after merge if no successor phase branch depends on it

## Source Phase Summary

- Goal: persist stage, attempt, operation, output, artifact, and stage-lease authority behavior in the private repository.
- Required scope: stage transition persistence, attempt allocation and terminal-state records, submitted-operation state compatibility, output commits, artifact facts, stage lease/fencing checks, stale commit rejection, and read models for later APIs and diagnostics.
- Required checkpoints: transition ordering, unique attempt allocation, lease renewal/expiry behavior, output commit idempotence/conflicts, artifact fact persistence, stale generation/fencing rejection, and no direct runtime use.
- Acceptance criteria: repository tests cover stage transitions, attempts, output commits, artifact facts, stale lease/generation rejection, and no runtime caller uses the repository directly.

## Current Source And Harness Findings

- `src/loom/authority/_repository.py` is private and already imports backend-neutral pipeline value models. Phase 6 should extend it rather than expose a new public store module.
- Phase 5 schema version is `2`. Adding stage lifecycle tables is a durable private schema change, so Phase 6 should bump the private repository schema version and reject version 2 repositories as unsupported older.
- `src/loom/pipeline/stores/sqlite_authority.py` has useful stage, attempt, lease, output commit, artifact fact, snapshot, and recovery patterns. Phase 6 should adapt the semantics to the cross-run service DB shape instead of reusing the old per-run database location.
- `read_models.py` already provides `StageAttempt`, `StageLifecycleSnapshot`, `LeaseRecord`, `OutputCommitRecord`, `ArtifactFactRecord`, `OutputCommit`, and `RecoveryRecord`. Reusing these avoids duplicate private value models.
- `RunStatus` does not need new values for this phase. `StageStatus` already includes the terminal states needed for failure/cancellation/stale behavior, so no enum change is expected.

## In-Scope Work

- Extend the private repository schema with cross-run stage tables for stage state, attempts, stage leases, output commits, artifact facts, and supporting indexes.
- Bump the private authority repository schema version to the next version and update compatibility tests for older version 2 repositories.
- Add private methods for stage transition, attempt allocation with optional stage lease, stage lease renew/release/fail, terminal attempt recording, output commit recording, and stage snapshot/read-model assembly.
- Enforce stage transition preconditions, expected run revision checks, stale service generation checks when provided, stale or foreign stage fencing tokens, expired stage leases, duplicate output commit rejection, and terminal stage/attempt conflicts.
- Include stage attempts, active stage leases, latest output commit, and artifact facts in `open_run` snapshots.
- Add package, unit, contract, and integration tests for stage lifecycle semantics.

## Out-of-Scope Work

- FastAPI mutation routes, HTTP status mapping, client transport behavior, readiness route repository probing, and supervisor process commands.
- Runtime runner/worker/SLURM caller migration.
- Workspace coordination, resource admission leases, registry files, and offline evidence manifests.
- Public exports from `loom.authority`, `loom.pipeline.stores`, or CLI packages for the private repository.

## Assumptions

- Private repository schema version `3` can represent the first stage lifecycle schema. Repositories stamped with version `2` are rejected rather than migrated in this phase.
- Stage attempts use existing `StageAttempt` and `LeaseRecord` models, with stage lease IDs persisted in a stage-specific lease table.
- Output commits use existing `OutputCommitRecord` and `ArtifactFactRecord` models. Materialized refs can remain empty until a later phase needs richer references.
- Stale generation checks are optional private method parameters that compare against the persisted repository service generation when supplied.

## Scope Contract

The repository remains private to `loom.authority._repository`. Stage methods may return backend-neutral value records, but no public package root should import the repository module. Importing `loom.authority` must remain lightweight.

Stage mutations are optimistic and fenced. Mutations that receive `expected_revision` compare both sequence and token with the current run revision. Mutations that receive `service_generation` compare it with repository metadata. Stage output and terminal-attempt writes require an active matching stage lease, owner, and fencing token, and must reject expired, released, failed, stale, or foreign leases before writing.

Stage snapshots must be read from durable rows, not reconstructed from test-only memory. A run snapshot may include stage records, attempts, active leases, latest output commits, and artifact facts, while materialized refs remain empty unless output commit data explicitly records them.

## Design Impact

- Maintainability: keeps the high-risk stage mutation state machine in one repository module before route code exists.
- Extensibility: stage attempts, leases, output commits, and artifact facts provide the durable facts needed by later API, diagnostics, runtime migration, and offline import phases.
- Domain neutrality: records describe generic Loom stages and artifacts, not research-domain concepts.
- Source-tree boundaries: service repository details remain private and runtime callers remain unchanged.

## Future Compatibility

The schema should leave room for deferred finalization, scheduler operation metadata, offline provenance, materialized refs, and resource admission without requiring public SQL compatibility. The private method names should be direct enough for Phase 7 route mapping to wrap without another repository redesign.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Keep schema version `2` and add tables silently | Run-only repositories would appear stage-capable even when required tables are missing. |
| Reuse `SQLitePerRunAuthorityStore` directly | It owns per-run DB paths and public-ish store behavior rather than the service-owned cross-run repository. |
| Implement route/protocol mapping now | Phase 7 owns service API mapping and client behavior. |
| Treat output commits as unfenced append-only artifact facts | Phase acceptance requires stale lease/fencing rejection and commit conflict behavior. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Private repository API remains SQLite-first | The roadmap chooses a local service DB first. | Hosted or non-SQLite authority backend is planned. |
| Stage repository behavior remains inaccessible to real clients | Phase 7 owns mutation API exposure. | FastAPI mutation route phase begins. |
| Materialized refs are not deeply modeled | Phase scope requires artifact facts and output commits, while richer materialized reference handling can follow runtime adoption needs. | Offline import or materialized-ref diagnostics require richer fields. |

## Reviewability

- Expected PR size and shape: large private repository extension plus focused unit, contract, and integration tests.
- Files and areas to inspect: `src/loom/authority/_repository.py`, stage lifecycle tests under `tests/unit/loom/authority`, contract tests, integration tests, and package import-boundary tests.
- Scope-control checks: no FastAPI route wiring, no runtime caller migration, no registry or supervisor behavior, no workspace/resource admission, no offline import, and no public repository exports.

## Implementation Steps

1. Extend schema/version checks with stage, attempt, stage lease, output commit, and artifact fact tables.
2. Add private helpers for service generation checks, stage rows, attempts, stage leases, output commits, artifact facts, and stage-aware snapshots.
3. Implement stage transition, attempt allocation, stage lease lifecycle, terminal attempt updates, and output commit recording.
4. Add stale revision, stale generation, stale fencing, lease expiry, duplicate commit, and terminal-state conflict checks.
5. Add package, unit, contract, and integration tests for stage lifecycle semantics and privacy.
6. Run targeted validation, then final `make validate-pr` and `make test-summary` before PR preparation.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `loom.authority` remains lightweight and does not import the private repository, `sqlite3`, or `loom.pipeline`; repository lifecycle symbols are not exported from the public package root.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/authority/test_repository_stage_lifecycle.py`
- Required assertions or deferral reason: schema version bump, older v2 rejection, stage transition validation, attempt allocation uniqueness, stage lease fencing/renewal/expiry, terminal attempt checks, duplicate output commit rejection, stale generation rejection, and artifact fact serialization.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_authority_repository_contract.py`
- Required assertions or deferral reason: private repository stage lifecycle outputs align with backend-neutral protocol/read-model records, and stale generation/fencing/conflict failures can map to existing protocol rejection categories without importing FastAPI.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/authority/test_repository_stage_lifecycle.py`
- Required assertions or deferral reason: file-backed multi-stage lifecycle sequences, retry/attempt allocation, output commit and artifact fact persistence across handles, expired stage lease recovery, stale generation rejection, and transaction rollback around stage writes.

### E2E Suite

- Status: deferred
- Expected paths: not required for this phase
- Required assertions or deferral reason: no CLI, supervisor process, FastAPI mutation route, runtime caller, or user workflow behavior changes.

### Opt-In Suites

- Status: deferred
- Markers affected: none expected
- Required assertions or deferral reason: no network, scheduler, external service, or long-running process is required.

## Risks

- Stage lifecycle logic can accidentally duplicate or diverge from existing per-run authority semantics.
- Weak stale generation or fencing checks would undermine later runner safety.
- Over-modeling submitted operations or resource admission would expand into later phases.
- Large private repository growth can reduce reviewability, so tests should pin the public behavior of each mutation slice.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/authority/_repository.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_repository_run_lifecycle.py tests/unit/loom/authority/test_repository_stage_lifecycle.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/integration/authority/test_repository_run_lifecycle.py tests/integration/authority/test_repository_stage_lifecycle.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/authority/_repository.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_repository_run_lifecycle.py tests/unit/loom/authority/test_repository_stage_lifecycle.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/integration/authority/test_repository_run_lifecycle.py tests/integration/authority/test_repository_stage_lifecycle.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_import_boundaries.py tests/unit/loom/authority/test_repository.py tests/unit/loom/authority/test_repository_run_lifecycle.py tests/unit/loom/authority/test_repository_stage_lifecycle.py tests/contracts/test_authority_repository_contract.py tests/integration/authority/test_repository.py tests/integration/authority/test_repository_run_lifecycle.py tests/integration/authority/test_repository_stage_lifecycle.py
```

Final PR-preparation commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache make validate-pr
UV_CACHE_DIR=/tmp/uv-cache make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: schema/version extension, stage state helpers, attempt allocation, stage lease lifecycle, terminal attempt/output commits, stage-aware snapshots, then privacy and suite coverage.
- Tests to run with each slice: unit tests after schema/stage helpers, contract tests after stale generation/fencing records, integration tests after output commit and snapshot persistence, package tests after import-boundary assertions.
- Decisions the executor must not revisit: repository stays private under `loom.authority`, schema version bumps to `3`, route/client mapping waits for Phase 7, runtime caller migration waits for later phases, and resource admission/offline import stay out of scope.
- Conditions that require stopping for the manager: need to expose repository symbols publicly, need to change public status enums, need to implement FastAPI route mapping, or inability to reject stale generation/fencing without broader protocol redesign.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-11 by managing agent after
  implementation and validation; no code changes were required after the final
  validation pass
- PR review: used on 2026-05-11 by managing agent; approved with no blocking
  or non-blocking findings
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed by managing agent on 2026-05-11.
- Final phase execution plan: completed by managing agent on 2026-05-11.
- Implementation summary: extended the private authority repository to schema
  version 3 with cross-run stage state, attempts, stage leases, output commits,
  and artifact facts. Added private stage transition, attempt allocation, stage
  lease renew/release/fail, terminal attempt, and output commit methods with
  expected-revision, service-generation, TTL, and fencing checks. Run snapshots
  now include durable stage attempts, active leases, latest commits, and
  artifact facts. The work stayed private to `loom.authority._repository` and
  did not add route, runtime, registry, supervisor, resource-admission, or
  offline-import behavior.
- Implementation validation: targeted `ruff`, `pyright`, and focused package,
  unit, contract, and integration pytest passed for the repository changes.
  Final `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` passed, including Ruff,
  Pyright, default pytest with 1237 passed, 18 skipped, 14 deselected,
  config-extra pytest with 420 passed and 1266 deselected, and package build.
  The first `make test-summary` run hit one unrelated flaky parallel-execution
  integration failure; the isolated test passed on rerun, and the final
  `UV_CACHE_DIR=/tmp/uv-cache make test-summary` rerun passed with overall
  1683 passed, 12 skipped, and 1277 deselected.
- Refinement summary: bounded implementation review inspected private import
  boundaries, schema-version behavior, stage-only scope, expected-revision and
  service-generation checks, stage lease fencing/expiry behavior, output commit
  conflicts, artifact fact persistence, stage-aware snapshots, and suite
  evidence. No scope or correctness blockers were found, and no code changes
  were required after the final validation pass.
- Blocker-resolution summary: not needed; 0/3 blocker-resolution passes used.
- PR preparation: PR #124 opened at
  https://github.com/samcantrill/loom/pull/124 against `develop` with
  `codex/authority-stage-lifecycle` as the head branch; target branch was
  verified immediately after creation.
- PR review: automated manager review verified the PR target, phase scope,
  private import boundary, schema versioning, stage lifecycle behavior,
  expected-revision and service-generation checks, lease fencing/expiry
  behavior, output commit and artifact fact persistence, stage-aware snapshots,
  PR body/test evidence, domain neutrality, and absence of future Phase 7 or
  runtime migration behavior. No blockers remain.
- Stack maintenance: root phase targets `develop`; no successor branch depends
  on `codex/authority-stage-lifecycle` yet.
- Remaining blockers: none known.
