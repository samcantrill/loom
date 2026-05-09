# Phase 2 Execution Plan: Per-Run SQLite Backend And Transaction Semantics

## Metadata

- Status: draft phase execution plan
- Feature focus: Persistence And Concurrency Foundation
- PR title: `Persistence And Concurrency Foundation - Phase 2: SQLite Run Backend And Transactions`
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
- Refine pass: pending for the expanded path.
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

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/authority.py` defines the `PerRunAuthorityStore` protocol and result records. `read_models.py` defines attempts, leases, commits, artifact facts, cleanup candidates, recovery records, snapshots, and warnings. `capabilities.py` defines capability declarations and unsupported diagnostics. `schema_policy.py` defines `AUTHORITY_SCHEMA_VERSION` and loud schema failure records. `coordination.py` is cross-run only and must not be implemented here. `local_runs.py` and `run_store.py` remain the legacy local-file run-store surface.
- Existing tests or harness behavior: `tests/support/authority_stores.py` has in-memory conformance stores for Phase 1. `tests/contracts/test_authority_store_contract.py` currently exercises the in-memory per-run contract and should be extended or reused for SQLite. `tests/package/test_pipeline_store_api.py` asserts exact store exports and that importing `loom.pipeline.stores` does not import `sqlite3`, `loom.runs`, CLI, or optional config/project code.
- Import-boundary or dependency constraints: the SQLite backend may import stdlib `sqlite3`, but root `loom.pipeline.stores` must stay import-light. Prefer a backend-specific module such as `loom.pipeline.stores.sqlite_authority` for the implementation and keep schema helpers private. If a root-level export is added, it must not make `import loom.pipeline.stores` import `sqlite3`.

## In-Scope Work

- Add a run-local SQLite per-run authority backend implementation under the pipeline store boundary, using only standard-library `sqlite3`.
- Add private path resolution from local `file://` run URIs to a private database location inside the run root; keep the exact path and table names private.
- Initialize and check a private v9 authority schema with metadata tied to `AUTHORITY_SCHEMA_VERSION`; fail loudly for missing, invalid, unsupported older, and unsupported newer active-state schemas.
- Implement short write transactions for run creation/opening, guarded run and stage transitions, monotonic attempt allocation, controller leases, stage leases, lease renewal/release/failure, submitted-operation upserts or writes, output commits, artifact facts, cleanup candidates that are identifiable from backend facts, audit rows, and revision increments.
- Implement fenced output commits so a stage can reach `SUCCEEDED` only when the active stage lease, attempt id, fencing token, output commit record, artifact facts, terminal stage status, and backend revision are committed atomically.
- Implement deterministic recovery scans for expired leases, abandoned attempts, interrupted submissions, and partial backend facts representable by the Phase 1 models.
- Declare SQLite per-run capabilities accurately, including local-clock lease semantics and explicit unsupported diagnostics for cross-run coordination, global counters, unsafe shared-filesystem assumptions, remote authority, and any materialization capability not actually implemented in Phase 2.
- Add documentation notes for SQLite limits around shared filesystems, high write concurrency, multi-host controllers, remote authority, private schema, and loud-fail schema policy.

## Out-of-Scope Work

- No serial runner write-path integration, public default backend flip, resume/status/catalog read-path swap, or legacy local-file fallback.
- No workspace/sweep coordination SQLite backend, trial/resource leases, global counters, or cross-run recovery.
- No backend CLI, repair command, mutation command, SQL command, export/import command, or user-facing snapshot workflow.
- No public SQL schema, table-name contract, migration framework, destructive migration, or old-run migration.
- No dynamic DAG behavior, bounded parallel scheduling, worker pool, or multi-controller execution.
- No new runtime dependencies and no network, SLURM, remote store, or hosted service requirement.
- No broad refactor of `LocalRunStore`, `RunCatalog`, execution runner modules, or CLI presentation modules.

## Assumptions

- The SQLite implementation surface may be importable from a backend-specific stores module, but the stable behavioral contract remains `PerRunAuthorityStore` and Phase 1 value models.
- `create_run()` may initialize the private authority database and its parent directory inside the run root. It must fail clearly when an authority database already exists with incompatible state.
- The run-local portability contract means the database path derives from the currently supplied run-root URI and no private schema detail should depend on an absolute database path. Returned record models should use the current `run_uri`; if preserving submitted-operation or record identity across ordinary run-root moves requires a Phase 1 contract change, stop for the manager.
- SQLite lease time is backend-owned local UTC time. The implementation should allow deterministic tests through an injectable clock or equivalent test-only time control while using Loom UTC timestamp helpers by default.
- Payload staging and checksum validation are future runner/materialization work. Phase 2 records authoritative commit and artifact facts for the `ArtifactRef` values it receives; it should not inspect payload files or create local materialization helpers beyond fields already present in Phase 1 records.

## Scope Contract

The SQLite backend must satisfy `PerRunAuthorityStore` for one run and only one run scope. It owns active state facts for that run: run status, stage status, attempts, controller/stage leases, submitted operations, output commits, artifact facts, cleanup candidates, audit evidence, backend revisions, recovery records, and snapshots. It must not implement workspace/sweep coordination or mutate cross-run facts.

The database schema is private. Reviewers may inspect it for correctness, but table names, column names, indexes, PRAGMAs, and SQL queries must not become documentation, CLI, catalog, runner, or public API contracts. Later phases should consume contract methods and read models, not SQLite internals.

All state-changing operations must advance a `BackendRevision` in the same transaction as the state change. Guarded transitions must compare the caller-supplied expected status with current backend state. Attempt allocation must be monotonic per stage under concurrent SQLite connections. Lease renewal, release, failure, and output commit must require matching owner and fencing token and must reject expired, released, failed, stale, or foreign leases.

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
- Scope-control checks: no public SQL docs, no broad local-store refactor, no `loom.runs` import from stores, no root store import of `sqlite3`, no runner hard swap, no CLI, no workspace/sweep records, no old-run migration, no status enum widening, and no materialized file truth path.

## Implementation Steps

1. Establish the backend module boundary, private path helper, connection setup, schema metadata, schema initialization/checking, and capability declarations while preserving root store import boundaries.
2. Add transaction/revision primitives and implement create/open/snapshot plus guarded run and stage transitions against the private schema.
3. Implement attempt allocation and controller/stage lease acquire, renew, release, fail, expiry filtering, and fencing-token checks with deterministic backend-owned time.
4. Implement submitted-operation persistence, audit row persistence with revision/sequence evidence, recovery scans, and cleanup-candidate listing for backend-identifiable facts.
5. Implement output commit transactions that validate active stage fencing and atomically record commit, artifact facts, terminal attempt/stage state, and revision.
6. Add package, unit, contract, and integration tests plus focused docs updates for SQLite limitations and private-schema/loud-fail policy.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py` and any existing package import-boundary tests if exports change.
- Required assertions or deferral reason: importing `loom.pipeline.stores` remains cheap and does not import `sqlite3`, `loom.runs`, CLI, project code, or optional config dependencies; the SQLite backend module imports without optional dependencies; any intentional backend export is stable and typed.

### Unit Suite

- Status: required.
- Expected paths: new tests under `tests/unit/loom/pipeline/stores/`, for example SQLite schema policy, transaction helpers, revision helpers, capability declarations, error mapping, submitted-operation persistence, event/audit evidence, lease time/fencing, and output-commit behavior.
- Required assertions or deferral reason: schema initialization records the current version; missing/invalid/older/newer schemas map to `AuthoritySchemaCheck`/failure diagnostics; every state mutation advances revision exactly with the transaction; stale status transitions fail; lease misuse fails; submitted records round-trip; output commits reject stale or foreign fences; SQLite-specific errors are mapped to store/authority errors without leaking raw SQL as public API.

### Contract Suite

- Status: required.
- Expected paths: extend `tests/contracts/test_authority_store_contract.py` or add a SQLite-specific contract companion that reuses the same per-run conformance assertions.
- Required assertions or deferral reason: SQLite satisfies `PerRunAuthorityStore`; supported per-run capabilities are present; unsupported cross-run/global/shared-unsafe capabilities are loud; create/open, transitions, attempts, leases, submitted operations, output commits, artifact facts, snapshots, recovery scans, cleanup candidates, and schema checks behave through Phase 1 models.

### Integration Suite

- Status: required.
- Expected paths: new tests under `tests/integration/pipeline/`, such as `test_sqlite_authority_backend.py` or `test_sqlite_authority_concurrency.py`.
- Required assertions or deferral reason: multiple SQLite connections or store instances contend deterministically for attempt allocation, stage lease acquisition, renewal/release/failure, output commit, submitted-operation writes, recovery scans, schema checks, cleanup candidates, and revisioned snapshots; ordinary run-root movement keeps the run-local authority database openable through the moved run URI; tests avoid timing-sensitive stress and use deterministic clocks/TTLs.

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
- Decisions the executor must not revisit: no public SQL schema; no runner or CLI integration; no workspace/sweep backend; no old-run migration; no legacy local-file fallback; no new status enum values; no third-party SQLite/ORM dependency; no root store import of `sqlite3`.
- Conditions that require stopping for the manager: Phase 1 protocol or value-model changes are required; run-root portability cannot be satisfied without changing public `run_uri` semantics; deterministic SQLite concurrency tests cannot be made reliable in the default suite; accepted capabilities would be misleading; implementation needs to touch execution runner, `loom.runs`, CLI, or workspace coordination to pass acceptance criteria.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete on 2026-05-10 by `loom_phase_planner`; expanded-path refine pass remains pending.
- Final phase execution plan: pending refine pass.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: none used.
- PR preparation: pending.
- Stack maintenance: no predecessor; branch targets `develop`.
- Remaining blockers: none recorded.
