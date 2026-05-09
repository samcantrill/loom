# Phase 1 Execution Plan: Authority Contracts, Schema Policy, And Compatibility Surface

## Metadata

- Status: pr_open; local validation recorded
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
- PR URL: https://github.com/samcantrill/loom/pull/101
- PR verification: `gh pr view 101 --json baseRefName,headRefName,state,url`
  returned base `develop`, head `codex/persistence-contracts`, state `OPEN`,
  and URL `https://github.com/samcantrill/loom/pull/101` on 2026-05-10.
- Merge eligibility: root phase PR; merge eligible after automated review, validation, and CI pass because it targets `develop`.
- Workflow path: expanded path because this phase defines backend-neutral public and semi-public contracts, schema policy, capability vocabulary, and read-model boundaries.
- Successor dependency notes: Phases 2-8 depend on the contract names, value models, authority boundaries, schema failure behavior, capability vocabulary, read-model shape, and workspace/sweep separation established here. No successor should query private SQLite tables, use legacy local files as active truth, or duplicate cross-run coordination inside per-run lifecycle state.
- Plan quality gate: passed on 2026-05-09 by `loom_plan_reviewer`; no blocking or non-blocking findings remained.
- Plan quality gate loop budget: initial review used; gate refinement not needed; confirmation review not needed.
- Draft pass: complete by `loom_phase_planner` in this artifact.
- Refine pass: complete on 2026-05-09 by `loom_phase_planner`; checked
  against implementation-plan v9, `docs/structure.md`, current
  `src/loom/pipeline` and `tests/` surfaces, and Phase 1 acceptance criteria.
- Setup limitations: branch/worktree creation used the manager-provided local `develop` state because the assignment recorded `7010204` as pushed to `origin/develop`; no `gh auth`, fetch, product-code validation, or broad checks were run during planning. Git ref creation required approved sandbox escalation because `.git/refs` was read-only in the default sandbox view.
- Blockers: none.

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

- Existing files or modules that constrain this phase:
  `src/loom/pipeline/stores/run_store.py` currently owns the local-file
  run-store protocols and `RunFreshnessRecord`; it should not be expanded in a
  way that makes `LocalRunStore` appear to satisfy v9 authority semantics. Add
  separate v9 authority contracts beside it under `src/loom/pipeline/stores/`.
  `src/loom/pipeline/stores/local_runs.py` remains the local filesystem
  implementation and is not the Phase 1 backend. `src/loom/pipeline/status.py`
  already keeps `RunStatus` and `StageStatus` coarse and includes `SUBMITTED`;
  do not add transient claim, lease, retry, commit, display, or not-selected
  statuses. `src/loom/pipeline/submitted.py` already provides a
  backend-neutral submitted-operation record and active/terminal predicates;
  extend or wrap it compatibly instead of creating a second submitted-work
  vocabulary. `src/loom/pipeline/locks.py` is a simple local run-lock record,
  not a backend-owned lease/fencing contract. `src/loom/pipeline/events.py`
  has audit event records with a sequence but no backend revision evidence;
  Phase 1 may add compatible evidence fields or companion records, but events
  remain audit-only. `src/loom/serialization/schema.py` supports version checks
  and optional migrations; v9 active-state schema policy needs dedicated
  loud-fail errors/results for unsupported old/new schemas and must not imply
  automatic destructive migration.
- Existing tests or harness behavior: package tests assert exact
  `loom.pipeline.stores.__all__` exports and import boundaries; contract tests
  use dummy `RunStore` and `LocalRunStore` protocol checks; unit tests cover
  status records, submitted-operation records, events, locks, local run store
  behavior, store errors, and serialization schema helpers; integration and e2e
  suites exercise current local-file runner/status/catalog behavior that this
  phase must not change.
- Import-boundary or dependency constraints: `loom.pipeline.stores` must remain
  import-light and not import CLI, `loom.runs`, project code, optional
  backends, or SQLite implementation modules. Execution orchestration remains
  in `loom.pipeline.execution`; `loom.runs` remains a derived query/projection
  facade. `docs/structure.md` is the source-tree boundary source, but the
  current tree is already much richer than its early skeleton, so update it
  only where Phase 1 adds real store-boundary modules or exports.

## In-Scope Work

- Add backend-neutral per-run authority contracts for run creation/opening, guarded lifecycle transitions, attempt allocation, run/controller leases, stage leases, submitted operations, output commits, artifact facts, audit events, revisions, recovery scans, cleanup candidates, and snapshot/read-model access.
- Add compact workspace/sweep coordination contracts for workspace or sweep identity, trial references, trial leases, resource leases, global concurrency counters, `run_uri` references, and recovery scans.
- Add capability vocabulary and result/diagnostic models covering atomic transitions, attempt allocation, lease acquire/renew/release/expiry, backend-owned lease time, atomic output commit, revisioned snapshots, recovery scans, consistent reads, materialization refs, per-run coordination, cross-run coordination, and unsupported operations.
- Add value models for stage attempts, controller/run leases, stage leases, submitted-operation detail or compatible adapters around the existing submitted model, output commits, artifact facts, backend revisions, lifecycle snapshots, structured reason codes, messages, detail payloads, recovery facts, cleanup candidates, static conditional outcomes, and read-model warnings.
- Add schema policy models and errors for current schema, unsupported older active-state schemas, unsupported newer schemas, and explicit future migration scope.
- Add audit event contract fields or companion records that carry backend revision or sequence evidence while preserving events as audit-only records.
- Add fake or in-memory conformance stores sufficient for contract tests without implementing SQLite.
- Update `docs/structure.md` and relevant feature docs when public exports or module boundaries are introduced.
- Keep any fake or in-memory store clearly test/support scoped unless a
  reusable source-level conformance helper is needed by later backend tests.

## Out-of-Scope Work

- No SQLite schema, database placement, transaction implementation, or real SQLite backend.
- No runner write-path integration, public backend hard swap, resume/status/catalog read-path swap, or legacy local-file migration.
- No bounded parallel execution, ready-stage scheduler, worker pool, or backend claim loop.
- No backend CLI, repair, mutation, SQL, export, import, or user-facing snapshot command.
- No full sweep runner, adaptive sweep algorithm, scheduler queue semantics, distributed controller, or dynamic DAG mutation.
- No changes that treat legacy status files, artifact indexes, events, or the derived run catalog as active truth for new runs.
- No mutation of current serial runner, status CLI, run catalog, or
  `LocalRunStore` behavior beyond import compatibility required by new
  contracts.

## Assumptions

- The primary implementation surface belongs under `loom.pipeline.stores`, with stable exports from `loom.pipeline.stores` only for contracts and models intended to be consumed by later phases.
- Existing coarse statuses, submitted-operation records, artifact refs, run URIs, and schema helpers should be reused where they fit rather than replaced with parallel concepts.
- Test-only fake stores may live under `tests/support` unless a source-level in-memory backend is needed to express a reusable conformance harness; either way, fake behavior must not imply a production backend.
- Protocol names and module names may be refined during implementation, but the authority boundaries, capability semantics, and no-SQLite-public-schema rule are fixed by v9.
- Plausible store-boundary modules are `authority`, `capabilities`,
  `coordination`, `read_models`, and `schema_policy` under
  `loom.pipeline.stores`; the executor may consolidate names if the public
  exports stay small, explicit, and reviewable.

## Scope Contract

The per-run authority contract is the only active state contract for one run. It owns run facts, stage facts, attempts, leases, submitted operations, output commits, artifact facts, cleanup candidates, backend revisions, recovery scans, and authoritative snapshots. It may expose materialized refs for payload/log/config/provenance files, but those files are not active truth.

The workspace/sweep coordination contract owns only cross-run facts. It may record workspace/sweep identity, trial references, trial/resource leases, global counters, and `run_uri` pointers. It must not copy per-stage lifecycle facts, mutate per-run stage state, or replace `RunCatalog`.

Capability declarations are correctness inputs, not informational labels. Explicit parallel, shared-filesystem, remote-capable, or cross-run coordination requests in later phases must be able to fail loudly when a backend lacks required capabilities. Unsupported capability results and schema failures must carry machine-readable codes plus safe diagnostic detail for API and CLI presentation.

Schema policy for v9 is loud-fail only for unsupported active-state schemas. Unknown newer schemas and unsupported older schemas must not be silently read, destructively migrated, or treated as legacy local-file fallback. Future migrations require explicit roadmap or phase scope.

`RunStatus` and `StageStatus` stay coarse. Attempts, leases, commits, recovery, reasons, owner, messages, display detail, static conditional outcomes, and submitted-operation detail belong in structured records or derived lifecycle snapshots. Do not add status enum values for transient claim, lease, retry, commit, display, or not-selected phases.

Events are audit records. They can carry backend revision or sequence evidence for diagnostics and ordering, but they must not be required to reconstruct the authoritative state machine.

Refined public-contract decisions:

- Keep existing `RunStore` and `LocalRunStore` as the current local-file store
  surface. New v9 authority protocols must be named so implementers cannot
  accidentally treat the legacy local store as capability-complete.
- Export only stable, later-phase-facing models from `loom.pipeline.stores`.
  Private helpers for fake stores, validation, or serialization should stay out
  of `__all__` unless a package test intentionally records them as supported.
- Prefer machine-readable enum or string-literal codes for capabilities,
  unsupported capability results, schema failure kinds, reason codes, and
  warnings. Human messages are diagnostic detail, not control flow.
- Lease and attempt records must include enough fencing identity to reject
  renew, release, fail, or commit requests from the wrong owner or stale
  attempt. Expiry semantics are based on backend-owned time, with fake stores
  using deterministic injected time.
- Output commit records must distinguish staged payload/materialization refs
  from authoritative committed facts and must expose cleanup-candidate facts
  for staged payloads left behind after failed backend commits.
- Read-model snapshots are authoritative views over backend facts and may carry
  warnings for missing materialized files, stale projections, unsupported
  schemas, or actively changing runs. They are not a user-facing export or
  snapshot workflow in this phase.

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

1. Choose the minimal store-boundary module and export layout, keep legacy
   `RunStore` semantics separate from v9 authority contracts, and update
   package/export tests before adding behavior-heavy models.
2. Add shared capability, schema-policy, diagnostic, reason, revision,
   lifecycle snapshot, recovery, cleanup, warning, and unsupported-result
   models with plain-data serialization and stable validation.
3. Add per-run authority protocols and fake/in-memory conformance behavior for
   guarded transitions, attempt allocation, run/controller leases, stage
   leases, submitted operations, output commits, artifact facts, audit revision
   evidence, snapshots, and recovery scans.
4. Add workspace/sweep coordination protocols and fake/in-memory conformance
   behavior for workspace/sweep identity, trial references, trial/resource
   leases, global counters, `run_uri` references, capability declarations, and
   recovery scans.
5. Add or adapt conformance contract tests around fake stores, then update docs
   for source-tree boundaries, authority roles, schema policy, and downstream
   compatibility.
6. Run targeted package, unit, and contract tests; leave integration, e2e, and
   opt-in suites deferred unless implementation adds a public smoke path beyond
   contract/import checks.

## Test Plan

### Package Suite

- Status: required.
- Expected paths: `tests/package/test_pipeline_store_api.py`,
  `tests/package/test_pipeline_api.py` if new models are intentionally exported
  from `loom.pipeline`, and existing import-boundary tests such as
  `tests/package/test_import_boundaries.py`.
- Required assertions or deferral reason: new contract/model exports are
  explicit, cheap to import, typed, and stable; `loom.pipeline.stores` does not
  import CLI, `loom.runs`, project code, optional backends, SQLite-specific
  implementation modules, or test fakes; `loom.__init__` remains cheap.

### Unit Suite

- Status: required.
- Expected paths: new focused tests under `tests/unit/loom/pipeline/stores/`
  for authority models, capabilities, schema policy, read models, fake-store
  helpers, and coordination models; existing tests such as
  `tests/unit/loom/pipeline/test_status.py`,
  `tests/unit/loom/pipeline/test_submitted.py`,
  `tests/unit/loom/pipeline/test_events.py`,
  `tests/unit/loom/pipeline/test_locks.py`,
  `tests/unit/loom/pipeline/stores/test_store_errors.py`, and
  `tests/unit/loom/serialization/test_schema.py` when touched.
- Required assertions or deferral reason: model validation and round-trip
  serialization; capability records and unsupported-capability results; schema
  failure mapping for current, older unsupported, and newer unsupported active
  schemas; read-model warnings; reason codes and detail payloads; attempt and
  lease identity/fencing fields; output commit and artifact fact validation;
  submitted-operation compatibility including cancellation and partial-work
  facts; audit revision evidence; cleanup/recovery/static-outcome records.

### Contract Suite

- Status: required.
- Expected paths: `tests/contracts/test_store_contract.py` plus new or updated conformance tests such as `tests/contracts/test_authority_store_contract.py` and `tests/contracts/test_workspace_coordination_contract.py`.
- Required assertions or deferral reason: fake or in-memory stores satisfy
  per-run authority protocols for create/open, guarded transitions, attempt
  allocation, lease acquire/renew/expire/release/fail with stale-token
  rejection, submitted-operation writes/inspection/summaries, output commit
  shape, artifact fact recording, revisioned snapshots, schema checks,
  recovery scan shape, cleanup candidates, unsupported capability failures,
  and read-model warnings; workspace/sweep fakes satisfy only cross-run
  identity/trial/resource/counter contracts and never expose per-stage
  mutation.

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
- Existing integration/e2e tests assume local-file state remains the live
  behavior; mitigate by keeping Phase 1 contract-only and avoiding runner,
  CLI, catalog, or `LocalRunStore` behavior changes.

## Validation Commands

Targeted development commands:

```sh
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/test_submitted.py tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/test_locks.py tests/unit/loom/pipeline/stores tests/unit/loom/serialization/test_schema.py
UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: export layout and package tests first; shared
  models/capabilities/schema errors second; per-run authority protocols and
  fake conformance third; workspace/sweep coordination contracts fourth; docs
  and final contract coverage last.
- Tests to run with each slice: package tests after export changes; unit model
  tests after each model group; contract tests after each fake protocol is
  added; targeted serialization/status/submitted/event/lock tests whenever
  existing models are touched.
- Decisions the executor must not revisit: no SQLite implementation; no runner
  hard swap; no active local-file fallback; no status enum widening for
  transient lifecycle details; existing `RunStore`/`LocalRunStore` remain
  legacy local-file store surfaces; events are audit-only; workspace/sweep
  coordination owns only cross-run facts; capability failures and unsupported
  schemas must be machine-readable and loud.
- Conditions that require stopping for the manager: the contract cannot be
  expressed without exposing SQLite table/schema details; implementation would
  require CLI, `loom.runs`, project-code, or SQLite-backend imports from store
  contracts; status enum widening appears necessary; workspace coordination
  needs per-stage state duplication; a real backend, runner behavior change, or
  public CLI change becomes necessary to satisfy tests.
- Expanded-path refinement notes: complete. The refined plan selects the
  pipeline store boundary, separates v9 authority contracts from the current
  local-file `RunStore`, keeps submitted-operation compatibility as a fixed
  requirement, requires deterministic fake-store conformance instead of SQLite,
  and confirms no Phase 1 blocker remains.

## Refinement And Review Budget Status

- Phase implementation refinement: used on 2026-05-09 by `loom_phase_refiner`
- PR review: unused
- Blocker resolution: 0/3 used

## Phase Refinement Report

### Metadata

- Phase: Phase 1 - Authority Contracts, Schema Policy, And Compatibility Surface
- Branch: `codex/persistence-contracts`
- Worktree: `/home/samcantrill/work/loom-worktrees/persistence-contracts`
- Phase execution plan: `docs/phases/persistence-contracts.md`
- Refiner: `loom_phase_refiner`
- Refinement date: 2026-05-09
- Pass type: implementation refinement
- Phase implementation refinement budget status after this pass: used
- Blocker-resolution budget status after this pass: unchanged; 0/3 used

### Refinement Scope

- Validation output reviewed: implementation evidence recorded in this plan,
  current branch diff against `develop`, phase commits, and rerun targeted
  package/unit/contract/Ruff/Pyright checks.
- Blocking issues caused by this phase: two phase-scoped contract coverage
  gaps were found. The in-memory per-run authority conformance store did not
  reject overlapping active stage leases or expired stage lease tokens for
  output commit fencing. Capability requirement diagnostics dropped detail
  from explicit unsupported capability declarations.
- Issues confirmed out of scope: SQLite implementation, runner integration,
  backend CLI, parallel execution, workspace sweep runner, migration, fallback
  behavior, public status enum changes, and PR preparation.

### Fixes Made

| Issue | Change | Evidence |
| --- | --- | --- |
| Expired or overlapping stage leases could remain usable in the per-run conformance fake. | Updated `InMemoryPerRunAuthorityStore` to reject overlapping active stage leases, treat expired leases as inactive for renewal/commit/snapshot checks, and record the committed attempt as `SUCCEEDED`. Added contract assertions for active-lease rejection, expired-token commit rejection, inactive snapshot lease detail, and terminal attempt status. | `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_authority_store_contract.py` passed: 3 tests. |
| Explicit unsupported capability records lost their declared diagnostic message/detail through `BackendCapabilitySet.require`. | Preserved unsupported capability record message/detail in the returned `UnsupportedCapability`, while retaining the machine-readable unsupported code and capability/scope detail. Added unit coverage for the declared-detail path. | `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/stores/test_authority_models.py` passed: 5 tests. |

### Tests Or Validation Re-Run

```text
command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py
result: passed, 34 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/test_submitted.py tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/test_locks.py tests/unit/loom/pipeline/stores tests/unit/loom/serialization/test_schema.py
result: passed, 131 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py
result: passed, 13 tests

command: UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores tests/support/authority_stores.py tests/unit/loom/pipeline/stores/test_authority_models.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py
result: passed with 0 errors

command: UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores/capabilities.py tests/support/authority_stores.py tests/unit/loom/pipeline/stores/test_authority_models.py tests/contracts/test_authority_store_contract.py
result: passed

command: make validate-pr
result: passed; Ruff, Pyright, default harness (980 passed, 17 skipped, 14 deselected), config-extra harness (416 passed, 1008 deselected), and uv build
```

### Remaining Blockers

- None.

### PR Preparation Handoff

- Completion notes updated in phase execution plan: yes.
- Budget status updated: phase implementation refinement used;
  blocker-resolution unchanged at 0/3 used; PR review unused.
- Final validation recommended: CI after PR creation; local PR-preparation
  validation is complete.
- Suite evidence still needed: none.

## Completion Notes

- Draft plan: complete in this artifact.
- Final phase execution plan: complete after expanded-path refinement on
  2026-05-09; scope-complete and implementable for Phase 1.
- Implementation summary: added backend-neutral Phase 1 store contracts under
  `loom.pipeline.stores` for capabilities, schema policy, authoritative
  per-run lifecycle authority, authoritative read-model records, and
  workspace/sweep coordination. The legacy local-file `RunStore` remains
  separate from `PerRunAuthorityStore`. Added test-support in-memory
  conformance stores for per-run and workspace coordination contracts, package
  export/import-boundary coverage, unit model coverage, contract tests, and
  docs updates for store boundaries, run-store authority semantics, coarse
  state detail, and sweep coordination separation. No SQLite backend, runner
  hard swap, backend CLI, parallel execution, workspace sweep runner,
  migration, or legacy fallback was implemented.
- Implementation validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_pipeline_api.py tests/package/test_import_boundaries.py`
    passed: 34 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/pipeline/test_status.py tests/unit/loom/pipeline/test_submitted.py tests/unit/loom/pipeline/test_events.py tests/unit/loom/pipeline/test_locks.py tests/unit/loom/pipeline/stores tests/unit/loom/serialization/test_schema.py`
    passed: 131 tests after the refinement coverage addition.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py`
    passed: 13 tests.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/loom/pipeline/stores tests/support/authority_stores.py tests/unit/loom/pipeline/stores/test_authority_models.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py`
    passed.
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pyright src/loom/pipeline/stores tests/support/authority_stores.py tests/unit/loom/pipeline/stores/test_authority_models.py tests/contracts/test_authority_store_contract.py tests/contracts/test_workspace_coordination_contract.py tests/package/test_pipeline_store_api.py tests/unit/loom/pipeline/stores/test_store_errors.py`
    passed with 0 errors.
  - `make validate-pr` passed after the refinement: Ruff, Pyright, default
    harness (980 passed, 17 skipped, 14 deselected), config-extra harness
    (416 passed, 1008 deselected), and `uv build`.
- Refinement summary: clarified current source/test constraints, store-boundary
  module choices, compatibility with submitted/event/schema/status helpers,
  fake-store conformance expectations, explicit edge cases, and suite-level
  obligations while preserving branch/base/target metadata. Implementation
  refinement pass used on 2026-05-09 to tighten capability diagnostics and
  fake-store lease/commit conformance coverage.
- Blocker-resolution summary: unchanged; 0/3 used.
- PR preparation: PR body refine complete; local validation complete; branch
  pushed and PR opened against `develop`.
- Stack maintenance: root PR targets `develop`; stack predecessor remains none.
- Remaining blockers: none.
- PR body draft pass: complete on 2026-05-09 by `loom_pr_preparer`.
  Created `docs/phases/persistence-contracts-pr-body.md` from
  `.codex/templates/phase-pr-body.md` and
  `.github/PULL_REQUEST_TEMPLATE.md` for the expanded-path draft pass. The
  draft confirms the branch/worktree, root target `develop`, no stack
  predecessor, contract-only Phase 1 scope, no future-phase implementation, and
  required package/unit/contract coverage. PR creation was intentionally
  deferred because the manager selected the expanded path.
- PR body refine pass: complete on 2026-05-10 by `loom_pr_preparer`.
  Verified `docs/phases/persistence-contracts-pr-body.md` against
  implementation-plan v9, this phase execution plan, the branch diff against
  `develop`, `.github/PULL_REQUEST_TEMPLATE.md`, and
  `.codex/templates/phase-pr-body.md`. Confirmed the branch remains
  `codex/persistence-contracts`, target branch remains `develop`, stack
  predecessor remains none, and Phase 1 remains contract-only with no SQLite
  backend, runner hard swap, backend CLI, parallel scheduler, sweep runner,
  migration, or legacy fallback implementation. The PR body summarizes only the
  implemented store contract surface, conformance fakes, package/unit/contract
  coverage, final local validation, and Phase 1 risks.
- PR body refine validation evidence:
  - `make validate-pr` passed on 2026-05-10: Ruff passed; Pyright passed with
    0 errors; default harness passed with 980 passed, 17 skipped, and 14
    deselected; config-extra passed with 416 passed and 1008 deselected; `uv
    build` produced the source distribution and wheel.
  - `make test-summary` passed on 2026-05-10 and wrote
    `build/test-summary.md` with generated timestamp
    `2026-05-09T14:06:54+00:00`: package 56 passed/1 skipped; unit 765
    passed/1 skipped; contract 83 passed/2 skipped; integration 64 passed/7
    skipped/10 deselected; e2e 37 passed/1 deselected; config-extra 416
    passed/1008 deselected; overall 1421 passed, 11 skipped, 1019 deselected,
    0 failed, 0 errors.
- PR creation and verification:
  - Branch push: `git push origin codex/persistence-contracts` succeeded on
    2026-05-10.
  - PR opened: https://github.com/samcantrill/loom/pull/101 with explicit base
    `develop`, head `codex/persistence-contracts`, title
    `Persistence And Concurrency Foundation - Phase 1: Authority Contracts And
    Compatibility Surface`, and body file
    `docs/phases/persistence-contracts-pr-body.md`.
  - PR verification: `gh pr view 101 --json baseRefName,headRefName,state,url`
    returned base `develop`, head `codex/persistence-contracts`, state `OPEN`,
    and URL `https://github.com/samcantrill/loom/pull/101`. The PR is a root
    phase PR and is merge-eligible after automated review, local validation,
    GitHub CI, and manager merge gates pass.
- PR body draft validation evidence:
  - `make test-summary` passed on 2026-05-09 and wrote
    `build/test-summary.md`: package 56 passed/1 skipped; unit 765 passed/1
    skipped; contract 83 passed/2 skipped; integration 64 passed/7 skipped/10
    deselected; e2e 37 passed/1 deselected; config-extra 416 passed/1008
    deselected; overall 1421 passed, 11 skipped, 1019 deselected, 0 failed, 0
    errors.
  - `git diff --check develop...HEAD` passed during PR-body draft.
