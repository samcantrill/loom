# Phase 2 Execution Plan: Per-Run SQLite Backend And Transaction Semantics

## Metadata

- Status: pr_open; PR opened and verified against `develop`
- Feature focus: Persistence And Concurrency Foundation
- PR title: `Persistence And Concurrency Foundation - Phase 2: SQLite Run Backend And Transactions`
- PR: https://github.com/samcantrill/loom/pull/102
- Branch: `codex/sqlite-run-backend`
- Worktree: `/home/samcantrill/work/loom-worktrees/sqlite-run-backend`
- Phase execution plan path: `docs/phases/sqlite-run-backend.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 2 - Per-Run SQLite Backend And Transaction Semantics
- Stack predecessor: none; Phase 1 merged into `develop`
- Base branch: `develop` at `ec8d951` (`docs: record v9 phase 1 merge`)
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after automated review, validation, and CI pass because it targets `develop`.
- Workflow path: expanded path because this phase implements private SQLite schema, transaction semantics, leases, recovery scans, schema policy, and data-loss/concurrency-sensitive behavior.
- Successor dependency notes: Phases 3-7 depend on the backend satisfying the Phase 1 per-run authority contract without leaking SQLite table names, file paths, or query shapes. Phase 8 remains a separate workspace/sweep coordination implementation and must not be pulled into this phase.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement not needed; confirmation review not needed.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: complete on 2026-05-10 by `loom_phase_planner`; confirmed scope-complete against Phase 1 contracts, current store boundaries, current tests, and Phase 2 acceptance criteria.
- Setup limitations: branch/worktree creation used the manager-recorded local `develop` state at `ec8d951`; no `gh auth`, fetch, full validation, or PR operation was run during planning. Worktree creation required approved sandbox escalation after the default sandbox could not create the namespaced git branch ref.
- Blockers: none.

## Objective

Implement the first run-local SQLite authoritative backend behind the Phase 1 `PerRunAuthorityStore` contract, with private schema, loud schema policy, short transaction boundaries, guarded transitions, attempt/lease/fencing semantics, submitted-operation persistence, atomic output-commit facts, revisions, recovery scans, and deterministic conformance and concurrency coverage.

## Full-Plan Context

V9 hard-swaps new active run state to a SQLite-first authoritative backend, but the swap is deliberately staged. Phase 1 established backend-neutral contracts and value models; Phase 2 proves those per-run contracts against a real SQLite implementation. Later phases must remain out of scope: Phase 3 builds materialization/read-model helpers, Phase 4 integrates serial write paths, Phase 5 flips public serial reads/defaults, Phase 6 adds read-only backend diagnostics, Phase 7 adds bounded parallel execution, and Phase 8 implements workspace/sweep coordination.

This phase creates the private state substrate only. Existing serial runner behavior, legacy local-file stores, run catalog projections, CLI status behavior, and workspace/sweep coordination must remain unchanged.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none; Phase 1 merged by PR #101.
- Why this base branch is correct: the manager recorded Phase 1 merge metadata on `develop` commit `ec8d951`, and this branch was created from that local `develop`.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is needed. If `develop` advances before PR preparation, rebase this root branch onto updated `develop` and keep the PR target as `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branches depend on it.

## Source Phase Summary

- Goal: implement the first per-run authoritative backend and transaction semantics behind the Phase 1 contracts using Python standard-library SQLite.
- Required scope: backend module under `loom.pipeline.stores`; private run-local database placement and schema; schema-version management; run, stage, attempt, lease, submitted-operation, output-commit, artifact-fact, cleanup-candidate, event/audit, revision, and snapshot records; guarded transactions; recovery scans; loud unsupported schema/capability diagnostics; and SQLite limitation documentation.
- Required checkpoints: no runner hard swap, no workspace/sweep coordination backend, no broad backend CLI, no public SQL schema, no old-run migration, and no local materialization helpers beyond backend facts needed by the contract.
- Acceptance criteria: SQLite satisfies `PerRunAuthorityStore`; the database travels with the run root; transitions and commits are guarded by backend state; attempt allocation is monotonic and concurrency-safe within SQLite local guarantees; one active non-expired stage lease owns a stage; lease expiry and recovery are deterministic; submitted operations, commits, artifact facts, cleanup candidates, revisions, snapshots, schema failures, and unsupported capabilities behave through Phase 1 models.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/authority.py` defines the `PerRunAuthorityStore` protocol and result records. `read_models.py` defines attempts, leases, commits, artifact facts, cleanup candidates, recovery records, snapshots, and warnings. `capabilities.py` defines capability declarations and unsupported diagnostics. `schema_policy.py` defines `AUTHORITY_SCHEMA_VERSION` and loud schema failure records. `run_uri.py` and `_paths.py` provide local `file://` path and containment helpers that should be reused rather than bypassed. `coordination.py` is cross-run only and must not be implemented here. `local_runs.py` and `run_store.py` remain the legacy local-file run-store surface.
- Existing tests or harness behavior: `tests/support/authority_stores.py` has in-memory conformance stores for Phase 1. `tests/contracts/test_authority_store_contract.py` currently exercises the in-memory per-run contract and should be extended, parameterized, or mirrored for SQLite. `tests/package/test_pipeline_store_api.py` asserts exact store exports and that importing `loom.pipeline.stores` does not import `sqlite3`, `loom.runs`, CLI, or optional config/project code. `tests/README.md` defines package, unit, contract, integration, e2e, and opt-in suite intent.
- Import-boundary or dependency constraints: the SQLite backend may import stdlib `sqlite3`, but root `loom.pipeline.stores` must stay import-light. Prefer a backend-specific module such as `loom.pipeline.stores.sqlite_authority` for the implementation and keep schema helpers private. If a root-level export is added, it must not make `import loom.pipeline.stores` import `sqlite3`, and the exact `__all__` package test must be updated deliberately.
- Phase 1 contract constraints for this phase: do not change the `PerRunAuthorityStore` method set, status enums, or read-model field shapes to make the backend easier. `PipelineEventRecord` exposes sequence evidence, not a public backend-revision field; any event-to-revision link may be persisted privately but must not require a Phase 1 model change. `SubmittedOperationRecord` carries `run_uri`, so SQLite reads after ordinary run-root movement must reconstruct returned submitted records with the current supplied run URI. There is no public cleanup-candidate write API yet, so cleanup candidates may only be recorded when representable through Phase 1 backend facts already in scope.

## In-Scope Work

- Add a run-local SQLite per-run authority backend implementation under the pipeline store boundary, using only standard-library `sqlite3`.
- Add private path resolution from local `file://` run URIs to a private database location inside the run root; keep the exact path and table names private and avoid persisting absolute run-root paths as authoritative identity.
- Initialize and check a private v9 authority schema with metadata tied to `AUTHORITY_SCHEMA_VERSION`; fail loudly for missing, invalid, unsupported older, and unsupported newer active-state schemas.
- Implement short write transactions for run creation/opening, guarded run and stage transitions, monotonic attempt allocation, controller leases, stage leases, lease renewal/release/failure, submitted-operation upserts or writes, output commits, artifact facts, cleanup candidates that are identifiable from backend facts, audit rows with sequence evidence and optional private revision linkage, and revision increments.
- Implement fenced output commits so a stage can reach `SUCCEEDED` only when the active stage lease, attempt id, fencing token, output commit record, artifact facts, terminal stage status, and backend revision are committed atomically.
- Implement deterministic recovery scans for expired leases, abandoned attempts, interrupted submissions, and partial backend facts representable by the Phase 1 models.
- Declare SQLite per-run capabilities accurately, including local-clock lease semantics and explicit unsupported diagnostics for cross-run coordination, global counters, unsafe shared-filesystem assumptions, remote authority, and any materialization capability not actually implemented in Phase 2.
- Add documentation notes for SQLite limits around shared filesystems, high write concurrency, multi-host controllers, remote authority, private schema, and loud-fail schema policy.

## Out-of-Scope Work

- No serial runner write-path integration, public default backend flip, resume/status/catalog read-path swap, or legacy local-file fallback.
- No workspace/sweep coordination SQLite backend, trial/resource leases, global counters, or cross-run recovery.
- No backend CLI, repair command, mutation command, SQL command, export/import command, or user-facing snapshot workflow.
- No public SQL schema, table-name contract, migration framework, destructive migration, or old-run migration.
- No Phase 1 protocol, read-model, submitted-operation, event-record, or status-enum changes unless the executor stops for the manager with a concrete contract blocker.
- No dynamic DAG behavior, bounded parallel scheduling, worker pool, or multi-controller execution.
- No new runtime dependencies and no network, SLURM, remote store, or hosted service requirement.
- No broad refactor of `LocalRunStore`, `RunCatalog`, execution runner modules, or CLI presentation modules.

## Assumptions

- The SQLite implementation surface may be importable from a backend-specific stores module, but the stable behavioral contract remains `PerRunAuthorityStore` and Phase 1 value models.
- `create_run()` may initialize the private authority database and its parent directory inside the run root. It must fail clearly when an authority database already exists with incompatible state.
- `check_schema()` should report missing, invalid, unsupported older, and unsupported newer SQLite authority schemas through `AuthoritySchemaCheck`/`AuthoritySchemaFailure` where possible. Mutating operations and `open_run()` should fail loudly before partial mutation when schema checks fail.
- The run-local portability contract means the database path derives from the currently supplied run-root URI and no private schema detail should depend on an absolute database path. Returned record fields whose Phase 1 models explicitly carry `run_uri` should use the current `run_uri`, including submitted-operation records after an ordinary local run-root move. `ArtifactRef.uri` values should be persisted as supplied in Phase 2; payload URI rewriting and missing-payload portability warnings are Phase 3/materialization concerns. If preserving record identity across ordinary run-root moves requires a Phase 1 contract change, stop for the manager.
- SQLite lease time is backend-owned local UTC time. The implementation should allow deterministic tests through an injectable clock or equivalent test-only time control while using Loom UTC timestamp helpers by default.
- Payload staging and checksum validation are future runner/materialization work. Phase 2 records authoritative commit and artifact facts for the `ArtifactRef` values it receives; it should not inspect payload files or create local materialization helpers beyond fields already present in Phase 1 records.

## Scope Contract

The SQLite backend must satisfy `PerRunAuthorityStore` for one run and only one run scope. It owns active state facts for that run: run status, stage status, attempts, controller/stage leases, submitted operations, output commits, artifact facts, cleanup candidates, audit evidence, backend revisions, recovery records, and snapshots. It must not implement workspace/sweep coordination or mutate cross-run facts.

The database schema is private. Reviewers may inspect it for correctness, but table names, column names, indexes, PRAGMAs, and SQL queries must not become documentation, CLI, catalog, runner, or public API contracts. Later phases should consume contract methods and read models, not SQLite internals.

All state-changing operations must advance a `BackendRevision` in the same transaction as the state change. Guarded transitions must compare the caller-supplied expected status with current backend state. Attempt allocation must be monotonic per stage under concurrent SQLite connections. Lease renewal, release, failure, and output commit must require matching owner and fencing token and must reject expired, released, failed, stale, or foreign leases.

The Phase 1 public contract is fixed for this phase. Returned models must be Phase 1 models, with no new status values and no public SQLite-specific fields. If the implementation needs a public event revision field, a cleanup-candidate write method, a materialization API, or a workspace/sweep primitive to satisfy Phase 2 tests, that is a blocker rather than a license to expand scope.

Schema policy is loud-fail only. The backend may initialize the current schema for a new run and may read the current schema, but it must not silently migrate, destructively rewrite, downgrade, or ignore unknown active-state schemas. Schema diagnostics should be machine-readable through Phase 1 schema/capability records without leaking SQL internals.

SQLite capabilities must be honest. The backend can claim local per-run coordination capabilities it actually implements, but shared-filesystem, multi-host, remote authority, cross-run coordination, and global counters must be unsupported or diagnostic-limited until later phases/backends provide stronger semantics.

## Design Impact

- Maintainability: keeps transaction and schema complexity inside one store-boundary backend while preserving Phase 1 contracts as the only external behavior surface.
- Extensibility: proves backend-neutral semantics against SQLite without blocking future Postgres, service, scheduler-aware, or remote-capable adapters.
- Domain neutrality: persists generic runtime facts only; no artifact payload interpretation, project-code import, domain metric handling, or scheduler-specific logic.
- Source-tree boundaries: backend code belongs under `loom.pipeline.stores`; execution orchestration stays in `loom.pipeline.execution`; `loom.runs` remains a derived projection; CLI and diagnostics remain future consumers.

## Future Compatibility

- Phase 3 can build authoritative read/model and materialization helpers from snapshot/revision behavior without querying private SQLite tables.
- Phase 4 can wire serial execution writes through the backend using guarded transitions, leases, attempts, submitted operations, and commits already validated here.
- Phase 5 can make backend-backed status/catalog reads the public default with no legacy local-file fallback.
- Phase 7 can use the same attempt/lease/fencing/recovery semantics for opt-in bounded local parallel execution.
- Stronger service or remote backends can reuse the capability vocabulary and failure diagnostics while replacing SQLite's local-clock and local-filesystem assumptions.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Adapting `LocalRunStore` files to mimic leases | File documents and locks cannot provide the transaction, compare-and-set, revision, and fencing semantics required by v9. |
| Publishing the SQLite schema as the backend contract | It would couple runner, catalog, diagnostics, bundles, and future backends to the first implementation. |
| Adding Postgres, a service process, or a third-party ORM | V9 explicitly chooses stdlib SQLite first and prohibits heavyweight runtime dependencies without separate design scope. |
| Running destructive migrations automatically | V9 schema policy is loud-fail only; future migrations require explicit roadmap scope. |
| Combining backend implementation with runner integration | Phase 2 needs a small reviewable transaction/conformance PR before Phases 4 and 5 change user-visible execution behavior. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| SQLite local-clock lease time is not distributed time | V9 SQLite is local or same-host only; central time belongs in a future stronger backend. | Shared-filesystem, multi-host, remote-controller, or scheduler-backed execution needs safe distributed lease expiry. |
| Private schema starts at one v9 version with loud-fail migration policy | Avoids hidden destructive migration during the first authoritative backend swap. | A future roadmap must preserve active v9 runs across schema changes. |
| Phase 2 cannot validate real staged payload cleanup without runner/materialization inputs | Payload staging is out of scope; Phase 4 owns actual staged payload commit/failure integration. | Runner integration introduces staged payload records or cleanup facts that the current backend contract cannot represent. |

## Reviewability

- Expected PR size and shape: moderate backend PR with one backend-specific stores module plus private helpers, package/unit/contract/integration tests, and focused docs updates. It should not include runner, CLI, catalog, or workspace coordination changes.
- Files and areas to inspect: `src/loom/pipeline/stores/` backend module and any private schema/transaction helpers; `src/loom/pipeline/stores/__init__.py` only if exports change; `tests/package/test_pipeline_store_api.py`; `tests/unit/loom/pipeline/stores/`; `tests/contracts/test_authority_store_contract.py` or a SQLite conformance companion; new SQLite integration tests under `tests/integration/pipeline/`; and docs that describe backend limits.
- Scope-control checks: no public SQL docs, no broad local-store refactor, no `loom.runs` import from stores, no root store import of `sqlite3`, no runner hard swap, no CLI, no workspace/sweep records, no old-run migration, no status enum widening, no Phase 1 protocol/model reshaping, and no materialized file truth path.

## Implementation Steps

1. Establish the backend module boundary, private path helper, connection setup, schema metadata, schema initialization/checking, and capability declarations while preserving root store import boundaries and avoiding an eager root `sqlite3` import.
2. Add transaction/revision primitives and implement create/open/snapshot plus guarded run and stage transitions against the private schema.
3. Implement attempt allocation and controller/stage lease acquire, renew, release, fail, expiry filtering, and fencing-token checks with deterministic backend-owned time.
4. Implement submitted-operation persistence, audit row persistence with public sequence evidence plus any private revision link, recovery scans, and cleanup-candidate listing for backend-identifiable facts.
5. Implement output commit transactions that validate active stage fencing and atomically record commit, artifact facts, terminal attempt/stage state, and revision.
6. Add package, unit, contract, and integration tests plus focused docs updates for SQLite limitations and private-schema/loud-fail policy.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py` and any existing package import-boundary tests if exports change.
- Required assertions or deferral reason: importing `loom.pipeline.stores` remains cheap and does not import `sqlite3`, `loom.runs`, CLI, project code, or optional config dependencies; the SQLite backend module imports without optional dependencies; any intentional backend export is stable, typed, and covered by an exact `__all__` update.

### Unit Suite

- Status: required.
- Expected paths: new tests under `tests/unit/loom/pipeline/stores/`, for example SQLite schema policy, transaction helpers, revision helpers, capability declarations, error mapping, submitted-operation persistence, event/audit evidence, lease time/fencing, and output-commit behavior.
- Required assertions or deferral reason: schema initialization records the current version; missing/invalid/older/newer schemas map to `AuthoritySchemaCheck`/failure diagnostics; every state mutation advances revision exactly with the transaction; stale status transitions fail; lease misuse fails; submitted records round-trip through Phase 1 models; audit appends expose sequence evidence without requiring a public revision field; output commits reject stale or foreign fences; SQLite-specific errors are mapped to store/authority errors without leaking raw SQL as public API.

### Contract Suite

- Status: required.
- Expected paths: extend `tests/contracts/test_authority_store_contract.py` or add a SQLite-specific contract companion that reuses the same per-run conformance assertions.
- Required assertions or deferral reason: SQLite satisfies `PerRunAuthorityStore`; supported per-run capabilities are present; unsupported cross-run/global/shared-unsafe capabilities are loud; create/open, transitions, attempts, leases, submitted operations, output commits, artifact facts, snapshots, recovery scans, cleanup candidates, and schema checks behave through Phase 1 models. The contract suite should be reused or parameterized so SQLite is checked against the same behavioral assertions as the in-memory conformance store, with extra SQLite-only cases kept out of the backend-neutral contract assertions.

### Integration Suite

- Status: required.
- Expected paths: new tests under `tests/integration/pipeline/`, such as `test_sqlite_authority_backend.py` or `test_sqlite_authority_concurrency.py`.
- Required assertions or deferral reason: multiple SQLite connections or store instances contend deterministically for attempt allocation, stage lease acquisition, renewal/release/failure, output commit, submitted-operation writes, recovery scans, schema checks, cleanup candidates representable from backend facts, and revisioned snapshots; ordinary run-root movement keeps the run-local authority database openable through the moved run URI and returns current-run-URI model fields, including submitted-operation `run_uri`; tests avoid timing-sensitive stress and use deterministic clocks/TTLs.

### E2E Suite

- Status: deferred.
- Expected paths: none for this phase.
- Required assertions or deferral reason: no public runner, CLI, status, catalog, or read-path behavior changes in Phase 2. E2E coverage begins when later phases wire the backend into user-visible execution/read surfaces.

### Opt-In Suites

- Status: deferred.
- Markers affected: none expected; do not add network, SLURM, slow, or timing-stress requirements.
- Required assertions or deferral reason: deterministic package/unit/contract/integration coverage is sufficient for the first SQLite backend. Optional stress tests can be considered later if Phase 7 parallel execution exposes nondeterministic timing risks.

## Risks

- SQLite file-locking semantics vary across filesystems; this phase must document local/same-host limits and fail loudly for shared-filesystem or remote assumptions rather than overclaim capabilities.
- Run-root portability can be undermined if the private schema stores absolute run paths or serialized records that cannot be reconstructed with the current `run_uri`.
- Contract gaps may appear around cleanup candidates, materialized refs, or audit revision evidence because Phase 1 intentionally kept the public surface compact.
- Accidentally satisfying a missing Phase 1 surface by adding public fields or methods would make Phase 2 unreviewable against its assigned scope; stop instead of widening the contract.
- Concurrency tests can become flaky if they rely on wall-clock timing instead of deterministic clocks, barriers, and bounded SQLite contention scenarios.
- Root-level exports can accidentally import `sqlite3` through `loom.pipeline.stores` and violate package import-boundary guarantees.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_store_api.py
uv run pytest tests/unit/loom/pipeline/stores/test_sqlite_authority.py
uv run pytest tests/contracts/test_authority_store_contract.py
uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py
make test-package
make test-unit
make test-contract
make test-integration
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: backend module/import boundary first; schema and schema-policy checks second; transaction/revision plus create/open/snapshot third; attempts/leases/fencing fourth; submitted/audit/recovery/cleanup fifth; output commits and artifact facts sixth; tests and docs alongside each slice.
- Tests to run with each slice: package import-boundary test after module/export changes; unit tests after schema/transaction/lease/commit slices; contract tests once core methods pass; integration concurrency tests after multi-connection behavior is implemented.
- Decisions the executor must not revisit: no public SQL schema; no runner or CLI integration; no workspace/sweep backend; no old-run migration; no legacy local-file fallback; no new status enum values; no third-party SQLite/ORM dependency; no root store import of `sqlite3`; no Phase 1 protocol/model expansion.
- Conditions that require stopping for the manager: Phase 1 protocol or value-model changes are required; run-root portability cannot be satisfied without changing public `run_uri` semantics; deterministic SQLite concurrency tests cannot be made reliable in the default suite; accepted capabilities would be misleading; implementation needs to touch execution runner, `loom.runs`, CLI, or workspace coordination to pass acceptance criteria; cleanup-candidate or audit-revision acceptance cannot be represented through current Phase 1 models.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-10 by `loom_phase_refiner`
- PR body draft: complete on 2026-05-10 by `loom_pr_preparer`; artifact at
  `docs/phases/sqlite-run-backend-pr-body.md`
- PR body refine: complete on 2026-05-10 by `loom_pr_preparer`; verified
  against the final diff, validation evidence, acceptance criteria, scope
  boundaries, and future-phase exclusions
- PR review: used on 2026-05-10 by the single PR review that found the
  post-commit attempt-allocation blocker; this blocker-resolution pass did not
  reset or rerun the PR-review budget
- Blocker resolution: 1/3 used on 2026-05-10 for the post-output-commit
  attempt-allocation regression in `SQLitePerRunAuthorityStore`

## Completion Notes

- Draft plan: complete on 2026-05-10 by `loom_phase_planner`.
- Final phase execution plan: refined and scope-complete on 2026-05-10; ready for `loom_phase_executor`.
- Implementation summary: added `loom.pipeline.stores.sqlite_authority.SQLitePerRunAuthorityStore` as a backend-specific, non-root-exported stdlib-SQLite implementation of the Phase 1 `PerRunAuthorityStore` contract. The backend creates a private run-local authority database, checks loud schema policy, declares supported per-run and unsupported cross-run/materialization capabilities, uses short `BEGIN IMMEDIATE` transactions for revisions and guarded mutations, allocates monotonic stage attempts, enforces controller/stage leases with owner/fencing/expiry checks, persists submitted operations with current-run-URI reconstruction, records audit events with sequence evidence and private revision linkage, atomically commits stage output facts behind active stage leases, reconstructs revisioned snapshots, filters expired leases from active snapshots, and scans for expired leases, abandoned attempts, and active submitted-operation recovery facts. No runner integration, root store export, public backend default, CLI, workspace/sweep backend, public SQL schema, status enum change, or Phase 1 contract/model expansion was added.
- Implementation validation:
  - `uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_sqlite_authority_backend.py` - passed, 23 tests after the implementation refinement.
  - `uv run ruff check src/loom/pipeline/stores/sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/integration/pipeline/test_sqlite_authority_backend.py` - passed.
  - `uv run pyright src/loom/pipeline/stores/sqlite_authority.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/integration/pipeline/test_sqlite_authority_backend.py tests/contracts/test_authority_store_contract.py` - passed.
  - Earlier targeted package import-boundary check confirmed importing `loom.pipeline.stores` does not import `sqlite3`.
  - `make validate-pr` - passed; Ruff, Pyright, default harness, config-extra harness, and build completed successfully.
- Implementation refinement summary: one expanded-path `loom_phase_refiner` pass completed on 2026-05-10. The pass reviewed `AGENTS.md`, the v9 implementation plan, this phase plan, current commits/diff, and recorded validation evidence, then tightened only Phase 2 backend/test behavior. Fixes made: existing incomplete SQLite authority files now fail loudly instead of being silently initialized by `create_run`; schema checks validate the private schema shape without documenting it as public API; schema initialization now runs inside the write transaction used by run creation; expired leases cannot be released or failed; active stage leases block unleased attempt allocation; fenced output commits reject terminal stage states; and successful output commits release the stage lease in the same transaction so later recovery scans do not report a completed lease as expired. No runner integration, root store export, CLI, workspace/sweep backend, status enum change, public SQL contract, old-run migration, or Phase 1 protocol/model change was added.
- Blocker-resolution summary: pass 1/3 completed on 2026-05-10. The pass fixed
  `SQLitePerRunAuthorityStore.allocate_stage_attempt()` so the same SQLite
  write transaction rejects allocation when a stage already has an output
  commit or is in a terminal stage state before inserting a new attempt or
  upserting the stage to `RUNNING`. Focused unit coverage now proves a
  successful output commit is followed by rejected allocation and that the
  snapshot remains `SUCCEEDED` with the prior commit and artifact facts intact.
  Additional unit coverage checks terminal-stage allocation rejection. No
  runner integration, backend CLI, workspace/sweep coordination,
  migration/fallback behavior, status enum change, or Phase 1 protocol/model
  change was added.
- Blocker-resolution validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_sqlite_authority.py` - passed, 10 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_authority_store_contract.py` - passed, 6 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py` - passed, 4 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py` - passed, 5 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/sqlite_authority.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_sqlite_authority_backend.py` - passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores/sqlite_authority.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_sqlite_authority_backend.py` - passed, 0 errors.
  - `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` - passed; Ruff, Pyright,
    default harness, config-extra harness, and build completed successfully.
  - `UV_CACHE_DIR=/tmp/uv-cache make test-summary` - passed; generated
    `build/test-summary.md` at `2026-05-09T16:00:25+00:00` with 1439 passed,
    0 failed, 0 errors, 11 skipped, 1037 deselected, and 130.10s overall
    duration.
- PR preparation: draft pass complete on 2026-05-10 by `loom_pr_preparer`.
  Expanded-path PR body refine pass complete on 2026-05-10 by
  `loom_pr_preparer`; the PR body at
  `docs/phases/sqlite-run-backend-pr-body.md` was verified against the final
  diff, validation evidence, acceptance criteria, and Phase 2 scope boundaries.
- PR facts confirmed during PR preparation: head branch
  `codex/sqlite-run-backend`; target branch `develop`; stack predecessor none;
  root phase PR; PR https://github.com/samcantrill/loom/pull/102; title
  `Persistence And Concurrency Foundation - Phase 2: SQLite Run Backend And Transactions`;
  merge eligibility remains target-branch, automated review, validation, and
  CI dependent.
- Draft-pass scope confirmation: final diff is limited to
  `src/loom/pipeline/stores/sqlite_authority.py`,
  `tests/contracts/test_authority_store_contract.py`,
  `tests/unit/loom/pipeline/stores/test_sqlite_authority.py`,
  `tests/integration/pipeline/test_sqlite_authority_backend.py`,
  `docs/features/run-store.md`, and this phase's artifacts. The implementation
  matches Phase 2 and does not include runner integration, public default or
  read-path flips, CLI/catalog integration, workspace/sweep coordination,
  public SQL schema, old-run migration, status enum changes, root store export
  changes, or Phase 1 protocol/model expansion.
- PR-preparation validation:
  - `make validate-pr` - passed on 2026-05-10 local time during PR-body
    refine; Ruff, Pyright, default harness, config-extra harness, and build
    completed successfully.
  - `make test-summary` - passed on 2026-05-10 local time during PR-body
    refine; generated `build/test-summary.md` at
    `2026-05-09T15:41:06+00:00` with 1437 passed, 0 failed, 0 errors,
    11 skipped, 1035 deselected, and 129.86s overall duration.
  - Suite evidence: package 56 passed / 1 skipped; unit 774 passed /
    1 skipped; contract 86 passed / 2 skipped; integration 68 passed /
    7 skipped / 10 deselected; e2e 37 passed / 1 deselected; config-extra
    416 passed / 1024 deselected.
  - GitHub checks were pending at PR opening; the managing agent owns CI
    polling after this PR-preparation pass.
- Stack maintenance: no predecessor; branch targets `develop`.
- PR opened: https://github.com/samcantrill/loom/pull/102
- PR verification: `gh pr view 102 --json baseRefName,headRefName,state,url`
  returned `baseRefName=develop`, `headRefName=codex/sqlite-run-backend`,
  `state=OPEN`, and `url=https://github.com/samcantrill/loom/pull/102`. The
  base matches the recorded target branch and this is a root phase PR with no
  stack predecessor.
- Remaining blockers: none recorded for PR-body refine or PR opening.

## Phase Refinement Report

### Metadata

- Phase: Phase 2 - Per-Run SQLite Backend And Transaction Semantics
- Branch: `codex/sqlite-run-backend`
- Worktree: `/home/samcantrill/work/loom-worktrees/sqlite-run-backend`
- Phase execution plan: `docs/phases/sqlite-run-backend.md`
- Refiner: `loom_phase_refiner`
- Refinement date: 2026-05-10
- Pass type: implementation refinement
- Phase implementation refinement budget status after this pass: used
- Blocker-resolution budget status after this pass: unchanged; 0/3 used

### Refinement Scope

- Validation output reviewed: executor-recorded targeted pytest/Ruff/Pyright and `make validate-pr` evidence; current refinement reran targeted package/unit/contract/integration pytest, targeted Ruff, targeted Pyright, and `make validate-pr`.
- Blocking issues caused by this phase: incomplete existing SQLite schemas could be silently initialized; expired leases could be released/failed; an active stage lease did not block unleased attempt allocation; output commit could override terminal stage state; successful output commit left the lease active and later recoverable as expired.
- Issues confirmed out of scope: runner integration, public backend hard swap, backend CLI, workspace/sweep coordination backend, migration/fallback behavior, status enum changes, and Phase 1 protocol/model changes.

### Fixes Made

| Issue | Change | Evidence |
| --- | --- | --- |
| Existing partial SQLite authority files could be accepted during `create_run`. | Distinguish missing databases from existing databases, validate private schema shape, and run initialization inside the create-run write transaction. | New unit coverage for incomplete existing schema; targeted pytest and `make validate-pr` passed. |
| Expired leases could be released or failed. | Added expiry rejection to lease finish paths. | Contract/unit coverage for expired release/fail; targeted pytest and `make validate-pr` passed. |
| Active leases could be bypassed by allocating an unleased attempt. | Stage attempt allocation now rejects any active non-expired stage lease. | Integration coverage across store instances; targeted pytest and `make validate-pr` passed. |
| Output commit could override terminal stage state and leave a completed lease active. | Output commit now requires a running/submitted stage and releases the stage lease in the same transaction as commit, artifact facts, terminal attempt/stage status, and revision. | Unit coverage for terminal-state rejection, lease release, and clean recovery after commit; targeted pytest and `make validate-pr` passed. |

### Tests Or Validation Re-Run

```text
command: uv run pytest tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_sqlite_authority_backend.py
result: passed, 23 tests

command: uv run ruff check src/loom/pipeline/stores/sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/integration/pipeline/test_sqlite_authority_backend.py
result: passed

command: uv run pyright src/loom/pipeline/stores/sqlite_authority.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/integration/pipeline/test_sqlite_authority_backend.py tests/contracts/test_authority_store_contract.py
result: passed, 0 errors

command: make validate-pr
result: passed; Ruff passed, Pyright passed, default harness passed with 996 passed / 17 skipped / 14 deselected, config-extra harness passed with 416 passed / 1024 deselected, and uv build succeeded
```

### Remaining Blockers

- None recorded.

### PR Preparation Handoff

- Completion notes updated in phase execution plan: yes
- Budget status updated: yes; phase implementation refinement used, PR body
  draft complete, PR body refine complete, blocker-resolution unchanged at
  0/3 used, PR review unused
- Final validation recommended: completed during PR-body refine with
  `make validate-pr` and `make test-summary`; rerun only if implementation or
  tests change after this PR-preparation pass
- Suite evidence still needed: none for this PR-preparation pass
- PR opened and verified: yes; PR #102 targets `develop` from
  `codex/sqlite-run-backend`

## Blocker Resolution Report

### Metadata

- Phase: Phase 2 - Per-Run SQLite Backend And Transaction Semantics
- Branch: `codex/sqlite-run-backend`
- Worktree: `/home/samcantrill/work/loom-worktrees/sqlite-run-backend`
- Phase execution plan: `docs/phases/sqlite-run-backend.md`
- Pass type: blocker resolution, 1/3
- Blocker-resolution date: 2026-05-10
- PR: https://github.com/samcantrill/loom/pull/102
- PR review budget status: used by the single PR review that found this
  blocker; not reset or rerun by this pass
- Blocker-resolution budget status after this pass: 1/3 used

### Blocker

- `SQLitePerRunAuthorityStore.allocate_stage_attempt()` could allocate a new
  running attempt after `record_output_commit()` had successfully committed the
  stage. That regressed the authoritative snapshot from `SUCCEEDED` to
  `RUNNING` while the old output commit remained recorded, violating Phase 2
  durable commit and terminal-stage semantics.

### Fixes Made

| Issue | Change | Evidence |
| --- | --- | --- |
| Post-commit allocation could overwrite the stage snapshot to `RUNNING`. | `allocate_stage_attempt()` now checks for an existing output commit inside the same `BEGIN IMMEDIATE` transaction before inserting an attempt or upserting stage state. | New unit coverage commits output, rejects later allocation, and verifies the snapshot remains `SUCCEEDED` with the original commit and artifact facts. |
| Terminal stage state was not checked before attempt allocation. | `allocate_stage_attempt()` now rejects terminal stage states in the same transaction before inserting/upserting. | New unit coverage for terminal-stage allocation rejection. |

### Tests Or Validation Re-Run

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_sqlite_authority.py
result: passed, 10 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_authority_store_contract.py
result: passed, 6 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/pipeline/test_sqlite_authority_backend.py
result: passed, 4 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py
result: passed, 5 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/sqlite_authority.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_sqlite_authority_backend.py
result: passed

command: UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores/sqlite_authority.py tests/unit/loom/pipeline/stores/test_sqlite_authority.py tests/contracts/test_authority_store_contract.py tests/integration/pipeline/test_sqlite_authority_backend.py
result: passed, 0 errors

command: UV_CACHE_DIR=/tmp/uv-cache make validate-pr
result: passed; Ruff passed, Pyright passed, default harness passed with 998 passed / 17 skipped / 14 deselected, config-extra harness passed with 416 passed / 1026 deselected, and uv build succeeded

command: UV_CACHE_DIR=/tmp/uv-cache make test-summary
result: passed; generated build/test-summary.md at 2026-05-09T16:00:25+00:00 with 1439 passed, 0 failed, 0 errors, 11 skipped, 1037 deselected, and 130.10s overall duration
```

### PR State Checked

- `gh pr view 102 --json baseRefName,headRefName,state,url,statusCheckRollup`
  returned `baseRefName=develop`, `headRefName=codex/sqlite-run-backend`,
  `state=OPEN`, and
  `url=https://github.com/samcantrill/loom/pull/102`.
- The previously completed GitHub CI `checks` run had conclusion `SUCCESS` and
  completed at `2026-05-09T15:47:10Z` before this blocker-resolution commit;
  the pushed blocker-resolution commit requires fresh GitHub checks.

### Remaining Blockers

- None recorded for this scoped blocker after local validation.
