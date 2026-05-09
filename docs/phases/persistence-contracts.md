# Phase 1 Execution Plan: Authority Contracts, Schema Policy, And Compatibility Surface

## Metadata

- Status: draft phase execution plan
- Feature focus: Persistence And Concurrency Foundation
- PR title: `Persistence And Concurrency Foundation - Phase 1: Authority Contracts And Compatibility Surface`
- Branch: `codex/persistence-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/persistence-contracts`
- Phase execution plan path: `docs/phases/persistence-contracts.md`
- Full plan: `docs/implementation-plans/implementation-plan-v9.md`
- Source phase: Phase 1 - Authority Contracts, Schema Policy, And Compatibility Surface
- Stack predecessor: none
- Base branch: `develop` at `7010204` (`docs: record v9 plan quality gate`)
- Target branch: `develop`
- Merge eligibility: root phase PR; merge eligible after automated review, validation, and CI pass because it targets `develop`.
- Workflow path: expanded path because this phase defines backend-neutral public and semi-public contracts, schema policy, capability vocabulary, and read-model boundaries.
- Successor dependency notes: Phases 2-8 depend on the contract names, value models, authority boundaries, schema failure behavior, capability vocabulary, read-model shape, and workspace/sweep separation established here. No successor should query private SQLite tables, use legacy local files as active truth, or duplicate cross-run coordination inside per-run lifecycle state.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement not needed; confirmation review not needed.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: pending for expanded path.
- Setup limitations: branch/worktree creation used the manager-provided local `develop` state because the assignment recorded `7010204` as pushed to `origin/develop`; no `gh auth`, fetch, product-code validation, or broad checks were run during planning. Git ref creation required approved sandbox escalation because `.git/refs` was read-only in the default sandbox view.
- Blockers: none known for the expanded-path refine handoff.

## Objective

Define Loom's backend-neutral authority contracts, schema-version policy, capability vocabulary, authoritative read-model shape, and compatibility boundaries before SQLite, runner write paths, status/catalog reads, diagnostics, parallel execution, or workspace coordination depend on them.

## Full-Plan Context

V9 replaces local-file active run state for new runs with a SQLite-first authoritative backend behind backend-neutral contracts. Phase 1 is the public and semi-public vocabulary layer: it must describe per-run authority, workspace/sweep coordination, capabilities, revisions, schema failures, leases, attempts, commits, submitted work, read models, and diagnostics without committing later phases to SQLite internals.

Later phases implement the SQLite backend, materialization/read models, serial write-path integration, public hard swap, backend diagnostics CLI, bounded parallel execution, and workspace/sweep coordination. Those later phases remain out of scope here: this phase should create contracts and conformance fakes only, not a real SQLite backend, runner hard swap, backend CLI, parallel scheduler, or sweep runner.

## Stack Context

- Root or stacked phase: root phase.
- Current predecessor branch or PR: none.
- Why this base branch is correct: v9 has no earlier phase branch, and the manager recorded local `develop` at the pushed plan-quality-gate commit `7010204`.
- Retarget/rebase plan after predecessor merge: no predecessor retarget is needed. If `develop` advances before PR preparation, rebase this root branch onto updated `develop` and keep the PR target as `develop`.
- Branch cleanup constraints: branch can be deleted after merge if no successor branches depend on it.

## Source Phase Summary

- Goal: define backend-neutral authority contracts, schema policy, capability vocabulary, read-model shape, and compatibility boundaries before behavior depends on them.
- Required scope: per-run authority protocols, compact workspace/sweep coordination protocols, capability models, value models for attempts/leases/submissions/commits/artifact facts/revisions/snapshots/reasons/recovery/cleanup/static outcomes, authoritative read-model contracts, schema-version errors, audit event records with revision evidence, diagnostic/error records, fake or in-memory conformance stores, and documentation updates when module boundaries or public exports change.
- Required checkpoints: keep `RunStatus` and `StageStatus` coarse; make unsupported capability and schema failures machine-readable; keep stores independent of CLI and project code; keep workspace/sweep coordination limited to cross-run facts; avoid exposing SQLite schema, runner behavior, parallel execution, backend CLI, export/snapshot commands, full sweep execution, or dynamic DAG condition language.
- Acceptance criteria: contracts express create/open, guarded transitions, attempt allocation, lease ownership/renewal/expiry/release/failure, atomic output commits, artifact facts, revisioned snapshots, schema checks, recovery scans, submitted operations, workspace trial/resource/counter records, capability declarations, loud unsupported results, and derived lifecycle detail without widening status enums or making events/catalogs authoritative.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/stores/run_store.py` currently owns file-store protocols and a `RunFreshnessRecord`; `src/loom/pipeline/stores/local_runs.py` is the local filesystem implementation and should not be mistaken for the v9 authority backend; `src/loom/pipeline/status.py` already keeps `RunStatus` and `StageStatus` coarse and includes `SUBMITTED`; `src/loom/pipeline/submitted.py` already provides a backend-neutral submitted-operation record and active/terminal predicates that should be reused or evolved compatibly; `src/loom/pipeline/locks.py` is a simple local run-lock model, not a backend-owned lease contract; `src/loom/pipeline/events.py` has audit event records with sequence but no backend revision evidence; `src/loom/serialization/schema.py` supports version checks and migrations, but v9 schema policy requires loud unsupported-schema failures rather than automatic destructive migration.
- Existing tests or harness behavior: package tests assert store public exports and import boundaries; contract tests use dummy `RunStore` and `LocalRunStore` protocol checks; unit tests cover status records, submitted-operation records, events, local run store behavior, and serialization schema helpers; integration and e2e suites exercise current local-file runner/status/catalog behavior that this phase must not change.
- Import-boundary or dependency constraints: `loom.pipeline.stores` must remain import-light and not import CLI, project code, or `loom.runs`; new authority contracts should sit under the pipeline store boundary unless the refine pass confirms a narrower existing boundary; execution orchestration remains in `loom.pipeline.execution`; `loom.runs` remains derived query/projection code.

## In-Scope Work

- Add backend-neutral per-run authority contracts for run creation/opening, guarded lifecycle transitions, attempt allocation, run/controller leases, stage leases, submitted operations, output commits, artifact facts, audit events, revisions, recovery scans, cleanup candidates, and snapshot/read-model access.
- Add compact workspace/sweep coordination contracts for workspace or sweep identity, trial references, trial leases, resource leases, global concurrency counters, `run_uri` references, and recovery scans.
- Add capability vocabulary and result/diagnostic models covering atomic transitions, attempt allocation, lease acquire/renew/release/expiry, backend-owned lease time, atomic output commit, revisioned snapshots, recovery scans, consistent reads, materialization refs, per-run coordination, cross-run coordination, and unsupported operations.
- Add value models for stage attempts, controller/run leases, stage leases, submitted-operation detail or compatible adapters around the existing submitted model, output commits, artifact facts, backend revisions, lifecycle snapshots, structured reason codes, messages, detail payloads, recovery facts, cleanup candidates, static conditional outcomes, and read-model warnings.
- Add schema policy models and errors for current schema, unsupported older active-state schemas, unsupported newer schemas, and explicit future migration scope.
- Add audit event contract fields or companion records that carry backend revision or sequence evidence while preserving events as audit-only records.
- Add fake or in-memory conformance stores sufficient for contract tests without implementing SQLite.
- Update `docs/structure.md` and relevant feature docs when public exports or module boundaries are introduced.

## Out-of-Scope Work

- No SQLite schema, database placement, transaction implementation, or real SQLite backend.
- No runner write-path integration, public backend hard swap, resume/status/catalog read-path swap, or legacy local-file migration.
- No bounded parallel execution, ready-stage scheduler, worker pool, or backend claim loop.
- No backend CLI, repair, mutation, SQL, export, import, or user-facing snapshot command.
- No full sweep runner, adaptive sweep algorithm, scheduler queue semantics, distributed controller, or dynamic DAG mutation.
- No changes that treat legacy status files, artifact indexes, events, or the derived run catalog as active truth for new runs.

## Assumptions

- The primary implementation surface belongs under `loom.pipeline.stores`, with stable exports from `loom.pipeline.stores` only for contracts and models intended to be consumed by later phases.
- Existing coarse statuses, submitted-operation records, artifact refs, run URIs, and schema helpers should be reused where they fit rather than replaced with parallel concepts.
- Test-only fake stores may live under `tests/support` unless a source-level in-memory backend is needed to express a reusable conformance harness; either way, fake behavior must not imply a production backend.
- Protocol names and module names may be refined during implementation, but the authority boundaries, capability semantics, and no-SQLite-public-schema rule are fixed by v9.

## Scope Contract

The per-run authority contract is the only active state contract for one run. It owns run facts, stage facts, attempts, leases, submitted operations, output commits, artifact facts, cleanup candidates, backend revisions, recovery scans, and authoritative snapshots. It may expose materialized refs for payload/log/config/provenance files, but those files are not active truth.

The workspace/sweep coordination contract owns only cross-run facts. It may record workspace/sweep identity, trial references, trial/resource leases, global counters, and `run_uri` pointers. It must not copy per-stage lifecycle facts, mutate per-run stage state, or replace `RunCatalog`.

Capability declarations are correctness inputs, not informational labels. Explicit parallel, shared-filesystem, remote-capable, or cross-run coordination requests in later phases must be able to fail loudly when a backend lacks required capabilities. Unsupported capability results and schema failures must carry machine-readable codes plus safe diagnostic detail for API and CLI presentation.

Schema policy for v9 is loud-fail only for unsupported active-state schemas. Unknown newer schemas and unsupported older schemas must not be silently read, destructively migrated, or treated as legacy local-file fallback. Future migrations require explicit roadmap or phase scope.

`RunStatus` and `StageStatus` stay coarse. Attempts, leases, commits, recovery, reasons, owner, messages, display detail, static conditional outcomes, and submitted-operation detail belong in structured records or derived lifecycle snapshots. Do not add status enum values for transient claim, lease, retry, commit, display, or not-selected phases.

Events are audit records. They can carry backend revision or sequence evidence for diagnostics and ordering, but they must not be required to reconstruct the authoritative state machine.

## Design Impact

- Maintainability: creates one explicit authority vocabulary before backend and runner code can drift into separate state interpretations.
- Extensibility: keeps SQLite as the first backend implementation rather than the public contract, preserving room for Postgres, service, scheduler-aware, or remote-capable adapters.
- Domain neutrality: models must describe generic runtime facts such as stages, attempts, commits, artifacts, leases, submissions, and trials without interpreting domain artifacts or metrics.
- Source-tree boundaries: contracts and backend capabilities stay under the pipeline store boundary; execution keeps orchestration decisions; `loom.runs` and CLI remain consumers/projections, not authority owners.

## Future Compatibility

- Phase 2 can implement SQLite behind the per-run contract without exposing table names or SQL queries to runner, CLI, catalog, diagnostics, or bundle code.
- Phase 3 can build the materialization/read-model layer from the same snapshot and warning contracts instead of inventing consumer-specific queries.
- Phases 4 and 5 can swap write and read paths to backend authority while preserving coarse status compatibility and no legacy fallback.
- Phase 7 can validate bounded local parallel execution through explicit claim, lease, commit, revision, and recovery capabilities.
- Phase 8 and v11 can implement cross-run trial/resource coordination without placing sweep policy inside per-run state.
- V10 bundles, v13/v14 remote stores, v15/v16 submitted/container/HPC work, and v17 reliability can consume read-model, submitted-operation, commit, recovery, and cleanup records without reading private SQLite tables.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| SQLite-specific public runner APIs | They would leak the first implementation into long-term contracts and make stronger backends harder to add. |
| Extending the legacy local-file `RunStore` as the v9 authority | Local files cannot provide the transaction, compare-and-set, revision, and lease semantics required by v9. |
| Widening status enums for attempts, leases, commits, retries, or not-selected outcomes | Coarse status compatibility is a v9 design decision; detailed lifecycle state belongs in structured records and snapshots. |
| Treating events, catalogs, or artifact index files as active truth | They are audit records, projections, or materialized views and would create split-brain state. |
| Deferring workspace/sweep coordination contracts until v11 | Cross-run lease and counter semantics need a boundary now so per-run authority is not overloaded later. |
| Letting v10 bundles define the first authoritative metadata read path | V9 status, catalog, diagnostics, and later bundle/export work need one backend-neutral read model first. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Fake or in-memory conformance stores cannot prove SQLite transaction behavior | Phase 1 is contract-only by design; Phase 2 owns real SQLite transactions and concurrent integration tests. | Phase 2 finds the contract cannot be implemented without changing public semantics. |
| Public/semi-public model vocabulary may be larger than current runner needs | Later v9 phases need attempts, leases, commits, revisions, read models, and coordination to avoid retrofitting incompatible fields. | A refine/review pass finds a model has no v9 consumer or can be derived without becoming a contract. |
| Schema migration policy is loud-fail only in v9 | The hard swap intentionally avoids hidden destructive migration during the first authoritative backend version. | A future roadmap requires preserving active v9 runs across schema changes. |

## Reviewability

- Expected PR size and shape: moderate contract/model PR with new or updated store-boundary modules, focused public exports, fake conformance harnesses, documentation updates, and package/unit/contract tests. It should not touch runner behavior except for import compatibility if needed.
- Files and areas to inspect: `src/loom/pipeline/stores/`, especially any new authority/capability/read-model/schema modules and `__init__.py`; `src/loom/pipeline/status.py`; `src/loom/pipeline/submitted.py`; `src/loom/pipeline/events.py`; `src/loom/pipeline/locks.py` only if compatibility wrappers are added; `src/loom/serialization/schema.py` only if shared schema helpers are extended; `docs/structure.md`; `docs/features/run-store.md`; `docs/features/state.md`; `docs/features/run-catalog.md`; `docs/features/sweeps.md`; `docs/features/reliability.md`; and corresponding tests.
- Scope-control checks: no SQLite implementation or SQL schema; no runner hard swap; no backend CLI; no old-run migration; no legacy local-file fallback; no new status values for transient lifecycle detail; no imports from CLI, project code, or `loom.runs` in store contracts; no workspace/sweep records that duplicate per-stage run state.

## Implementation Steps

1. Choose the minimal store-boundary module and export layout, then update package/export tests before adding behavior-heavy models.
2. Add shared authority capability, schema-policy, diagnostic, reason, revision, lifecycle snapshot, recovery, cleanup, and unsupported-result models with plain-data serialization and stable validation.
3. Add per-run authority protocols and test fakes for guarded transitions, attempt allocation, leases, submitted operations, output commits, artifact facts, audit revision evidence, snapshots, and recovery scans.
4. Add workspace/sweep coordination protocols and test fakes for trial references, trial/resource leases, global counters, `run_uri` references, capability declarations, and recovery scans.
5. Add or adapt conformance contract tests around fake stores, then update docs for source-tree boundaries, authority roles, schema policy, and downstream compatibility.
6. Run targeted package, unit, and contract tests; leave integration, e2e, and opt-in suites deferred unless implementation adds a public smoke path beyond contract/import checks.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`, `tests/package/test_pipeline_api.py` if new models are intentionally exported from `loom.pipeline`, and existing import-boundary tests such as `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: new contract/model exports are explicit, cheap to import, typed, and stable; `loom.pipeline.stores` does not import CLI, `loom.runs`, project code, optional backends, or SQLite-specific implementation modules; `loom.__init__` remains cheap.

### Unit Suite

- Status: required.
- Expected paths: new focused tests under `tests/unit/loom/pipeline/stores/` for authority models, capabilities, schema policy, read models, fake-store helpers, and coordination models; existing tests such as `tests/unit/loom/pipeline/test_status.py`, `tests/unit/loom/pipeline/test_submitted.py`, `tests/unit/loom/pipeline/test_events.py`, `tests/unit/loom/pipeline/stores/test_store_errors.py`, and `tests/unit/loom/serialization/test_schema.py` when touched.
- Required assertions or deferral reason: model validation and round-trip serialization; capability records and unsupported-capability results; schema failure mapping for current, older unsupported, and newer unsupported schemas; read-model warnings; reason codes and detail payloads; attempt and lease identity/fencing fields; output commit and artifact fact validation; submitted-operation compatibility; audit revision evidence; cleanup/recovery/static-outcome records.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_store_contract.py` plus new or updated conformance tests such as `tests/contracts/test_authority_store_contract.py` and `tests/contracts/test_workspace_coordination_contract.py`.
- Required assertions or deferral reason: fake or in-memory stores satisfy per-run authority protocols for guarded transitions, attempt allocation, lease acquire/renew/expire/release/fail, submitted-operation writes and summaries, output commit shape, revisioned snapshots, schema checks, recovery scan shape, unsupported capability failures, and read-model warnings; workspace/sweep fakes satisfy only cross-run trial/resource/counter contracts and never expose per-stage mutation.

### Integration Suite

- Status: deferred beyond import-boundary or conformance harness checks.
- Expected paths: none required unless implementation creates an integration-only import or contract harness.
- Required assertions or deferral reason: Phase 1 has no real backend, runner integration, status/catalog read swap, or user workflow. Cross-component behavior is covered by package and contract suites until SQLite and runner integration exist in later phases.

### E2E Suite

- Status: deferred.
- Expected paths: none.
- Required assertions or deferral reason: Phase 1 has no user-facing CLI/API behavior beyond imports and contracts, so full workflow tests would either duplicate existing local-file behavior or accidentally test future phases.

### Opt-In Suites

- Status: deferred.
- Markers affected: none.
- Required assertions or deferral reason: Phase 1 must not require network services, real clusters, hosted trackers, remote databases, or timing-sensitive concurrency stress tests.

## Risks

- Contract surface can sprawl before a real backend proves every method is needed; mitigate by keeping protocols small, grouping capabilities by required later-phase behavior, and using the expanded-path refine pass to trim unused public names.
- Existing submitted-operation models may overlap with new authority records; mitigate by adapting or extending them compatibly rather than creating a second submitted-work vocabulary.
- Per-run and workspace coordination can blur if both use leases and revisions; mitigate with separate protocols and tests that forbid workspace stores from mutating per-stage state.
- Schema helper reuse can accidentally imply automatic migration; mitigate with explicit unsupported-schema error tests and no migration tables in Phase 1.
- Fake conformance stores can hide transaction semantics; mitigate by documenting the limit and requiring Phase 2 SQLite conformance and concurrent integration coverage.
- Events or derived snapshots can be misread as authority; mitigate with model names, docs, and tests that keep transition authority on the backend contract.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/test_submitted.py tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/stores tests/unit/loom/serialization/test_schema.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: export layout and package tests first; shared models/capabilities/schema errors second; per-run authority protocols and fake conformance third; workspace/sweep coordination contracts fourth; docs and final contract coverage last.
- Tests to run with each slice: package tests after export changes; unit model tests after each model group; contract tests after each fake protocol is added; targeted serialization/status/submitted/event tests whenever existing models are touched.
- Decisions the executor must not revisit: no SQLite implementation; no runner hard swap; no active local-file fallback; no status enum widening for transient lifecycle details; events are audit-only; workspace/sweep coordination owns only cross-run facts; capability failures and unsupported schemas must be machine-readable and loud.
- Conditions that require stopping for the manager: the contract cannot be expressed without exposing SQLite table/schema details; implementation would require CLI or `loom.runs` imports from store contracts; status enum widening appears necessary; workspace coordination needs per-stage state duplication; a real backend or runner behavior change becomes necessary to satisfy tests.
- Expanded-path refinement notes: pending. The refine pass should review public/semi-public module names, field names, compatibility with existing `SubmittedOperationRecord`, capability vocabulary completeness, and whether any model can be private or deferred before implementation begins.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: complete in this artifact.
- Final phase execution plan: pending expanded-path refinement.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: pending.
- PR preparation: pending.
- Stack maintenance: pending.
- Remaining blockers: none known at draft time.
