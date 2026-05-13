# Phase 5 Execution Plan: Queue Records And SQLite Repository

## Metadata

- Status: planned
- Feature focus: Queue Service, Resource Pools, And Delegated Dispatch
- PR title: `Queue Service, Resource Pools, And Delegated Dispatch - Phase 5: Queue Records And SQLite Repository`
- Branch: `codex/queue-records-sqlite-repository`
- Worktree: `/home/samcantrill/work/loom-worktrees/queue-records-sqlite-repository`
- Phase execution plan path: `docs/phases/queue-records-sqlite-repository.md`
- Full plan: `docs/implementation-plans/implementation-plan-v11.md`
- Source phase: Phase 5, `v11` Queue Records And SQLite Repository
- Stack predecessor: none
- Base branch: `develop`
- Target branch: `develop`
- Merge eligibility: root main-v11 phase after Phase 4 merge and transition checkpoint; merge to `develop` after validation, review, and CI
- Workflow path: expanded path because this phase introduces a new public package, durable schema, and repository contract
- Successor dependency notes: Phase 6 branches from `develop` if this phase merges, otherwise from this branch after PR open/validation
- Plan quality gate: implementation-plan v11 gate passed on 2026-05-13 and the post-Phase 4 transition checkpoint is recorded
- Plan quality gate loop budget: already satisfied in the implementation plan
- Draft pass: completed locally on 2026-05-13
- Refine pass: completed locally on 2026-05-13 after source inspection of run-catalog SQLite patterns, schema helpers, package boundary tests, and queue planning notes
- Setup limitations: GitHub operations require approved network access; `uv` validation requires approved cache access outside the filesystem sandbox
- Blockers: none

## Objective

Create the first durable queue vocabulary and SQLite repository under top-level `loom.queue`, without adding queue service, controller, launch adapter, or authority-resource behavior.

## Full-Plan Context

This is the first main v11 queue phase after the `v10-post` prerequisite checkpoint. It must define queue-owned identity, enqueue-time launch intent, dispatch-attempt semantics, cancellation evidence slots, audit records, FIFO item selection, and restart-safe SQLite persistence so later service/controller/adapter phases can build without redefining stored records.

## Stack Context

- Root or stacked phase: root
- Current predecessor branch or PR: Phase 4 merged into `develop`
- Why this base branch is correct: Phase 4 merge metadata and transition checkpoint are on `develop`
- Retarget/rebase plan after predecessor merge: not applicable
- Branch cleanup constraints: delete after merge only when no successor branch depends on it

## Source Phase Summary

- Goal: define versioned queue pool, queue, run intent, item, dispatch handle, cancellation, and audit records plus a SQLite-backed queue repository.
- Required scope: public plain-data models and validation, SQLite schema and repository operations, FIFO item selection primitives for one queue per pool, and a minimal private scheduler-selection seam.
- Acceptance criteria: DB persistence and restart recovery; versioned records reject unsafe or unknown fields; repository operations support enqueue, claim, dispatch-handle persistence, terminal completion, cancellation, and recovery scans; launch contracts preserve drift-detection and delegated-verification fields.
- Explicit boundary: queue state stays separate from authority lifecycle truth and no queue code opens private authority storage.

## Current Source And Harness Findings

- `src/loom/runs/_sqlite.py` provides a small dependency-light SQLite pattern: lazy `sqlite3`, schema metadata, WAL best effort, busy timeout, and JSON payload storage for typed models.
- `src/loom/pipeline/submitted.py` provides useful versioned-record patterns via `load_versioned_document(...)`, strict unknown-field rejection, uppercase durable state values, and plain-data metadata.
- Existing package boundary tests assert root imports remain lightweight and subsystem roots should not pull optional/server layers eagerly.
- No `loom.queue` package exists yet, so this phase can shape a clean top-level package boundary before service, controller, or adapter code lands.
- The Phase 4 transition checkpoint confirms the prerequisite queue-facing authority/runtime contracts are stable and no Phase 5 refresh is required.

## In-Scope Work

- Add `src/loom/queue/` with public errors, versioned models, repository interfaces, SQLite repository implementation, and private FIFO selection helpers.
- Define versioned plain-data models for queue pools, queues, run intent, launch contracts, queue items, claims, dispatch handles, cancellation records, audit events, recovery records, and repository operation results where useful.
- Persist queue-owned `queue_item_id`, queue-owned `run_uri`, immutable enqueue-time launch contract, status, `dispatch_attempt`, claim ownership, dispatch handle, cancellation facts, timestamps, and audit entries.
- Implement repository operations for schema initialization, enqueue/idempotency, FIFO claim, dispatch-handle persistence, terminal completion, cancellation, audit listing, item reads, and recovery scans.
- Add one-queue-per-pool validation and an internal FIFO selector that is replaceable later without changing persisted item records.
- Add package, unit, contract, and integration tests for model validation/serialization, schema guards, FIFO selection, repository restart recovery, and package import boundaries.

## Out-of-Scope Work

- Queue service process, HTTP/client transport, Python controller, or daemon lifecycle.
- Real local or SLURM launch adapters.
- Authority resource leasing, admission, resource-limit validation, or run lifecycle mutation.
- CLI commands, supervisor integration, queue config YAML loading, retries, fairness, priorities, multi-queue routing, or external broker support.

## Assumptions

- Queue model state values use uppercase strings consistent with existing runtime state records.
- A queue item is whole-run only and owns a persisted `run_uri` before first handoff.
- `dispatch_attempt` starts at 1 for the first claim/dispatch lifecycle and only future explicit requeue/resubmit work may increment it.
- SQLite may store canonical model JSON alongside indexed columns; the public compatibility surface is the model contract and repository behavior, not table layout.
- Cancellation in Phase 5 records queue-side request/evidence slots only; adapter proof and authority cancellation are later-phase work.

## Scope Contract

The repository may own queue-local scheduling state and audit history only. It must not import `loom.authority`, private authority repository modules, pipeline executors, or config optional dependencies. Later phases may use public authority clients, but Phase 5 should stay persistence-focused and dependency-light.

## Design Impact

- Maintainability: establishes a separate `loom.queue` package with explicit model/repository ownership before service/controller code arrives.
- Extensibility: versioned launch contracts and dispatch handles preserve adapter-visible evidence slots without baking in local or SLURM launch behavior.
- Domain neutrality: records describe generic runs, pools, queues, resources, and adapter evidence rather than domain-specific workloads.
- Source-tree boundaries: SQLite details stay private to the queue package; public imports expose typed records and repository operations.

## Future Compatibility

The private FIFO selector should be replaceable by richer scheduler policy without changing queue item storage. Launch contracts should carry enough snapshot and verification fields for local drift checks in Phase 7 and delegated launch verification in Phase 8 without a schema break.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Store queue state in authority tables | The plan keeps queue policy separate from authority truth. |
| Persist unversioned dictionaries | Later phases need stable recovery and compatibility checks from the start. |
| Hard-code dispatch selection inside SQLite SQL only | A minimal selector seam keeps future policy work reviewable. |
| Add service/client/controller surfaces now | Phase 6 owns service and Python control; adding them here would blur review scope. |
| Mutate authority resource limits or leases | Managed resource dispatch belongs to Phase 7 and must use the Phase 3 read/reconcile contract. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Built-in repository is SQLite-only | It satisfies the first workspace-scoped durability target without dependencies | Queue write contention, distributed controllers, or site-wide queue usage outgrow SQLite |
| FIFO selector is private and simple | One queue per pool is the v11 MVP and avoids premature public scheduler API | Priority, fairness, borrowing, or resource-dependent policy becomes required |
| Cancellation evidence is queue-local only | Adapter proof and authority effects land in later phases | Phase 8/9 cancellation paths need richer proof fields |
| Schema migration is guard-only in v1 | There is no previous queue schema to migrate | A later queue schema version is introduced |

## Reviewability

- Expected PR size and shape: new queue package plus focused tests, with no queue service or adapter code.
- Files and areas to inspect: `src/loom/queue/`, package tests, queue model/contract tests, and SQLite repository integration tests.
- Scope-control checks: no `loom.authority._repository`, no queue service routes, no CLI, no launch adapter, no resource leasing.

## Implementation Steps

1. Add queue errors and versioned public model records with strict `from_dict(...)` and `to_dict(...)` behavior.
2. Add repository protocol/result shapes and private FIFO selection helper.
3. Implement the SQLite repository with schema metadata, indexed queue item columns, canonical JSON payloads, audit rows, and restart-safe reads.
4. Add package/import-boundary tests for `loom.queue`.
5. Add unit/contract tests for model serialization, unknown-field rejection, queue/pool validation, and selector behavior.
6. Add integration tests for SQLite enqueue, FIFO claim, dispatch handle persistence, completion, cancellation, recovery scans, schema guard, and restart recovery.
7. Run targeted suites, then full PR validation and summary.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: `loom.queue` imports cleanly, exports the intended public symbols, and does not import config, CLI, authority server/private repository, or executor layers eagerly.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/queue/test_queue_models.py`, `tests/unit/loom/queue/test_scheduler.py`
- Required assertions or deferral reason: versioned model serialization, unknown-field rejection, state validation, one-queue-per-pool validation, launch-contract drift/verification fields, and FIFO selection order.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_queue_records_contract.py`, `tests/contracts/test_queue_repository_contract.py`
- Required assertions or deferral reason: public queue record shape and repository operation expectations are stable for later phases.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/queue/test_sqlite_repository.py`
- Required assertions or deferral reason: SQLite schema initialization, enqueue/claim/dispatch/complete/cancel operations, restart recovery, schema-version guard, and recovery scans.

### E2E Suite

- Status: deferred
- Expected paths: not required
- Required assertions or deferral reason: no service, CLI, controller, or launch workflow is in scope.

### Opt-In Suites

- Status: deferred
- Markers affected: none
- Required assertions or deferral reason: no real SLURM, network scheduler, or site-specific dependencies are introduced.

## Risks

- The first queue model names may become sticky for later phases; keep them generic and plain-data based.
- SQLite indexes must support FIFO claim without pretending to solve future multi-controller fairness or broker-level concurrency.
- Repository terminal/cancellation states must not imply authority lifecycle truth.
- Public exports should remain lightweight and avoid importing `sqlite3` through the `loom.queue` root if possible.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import.py tests/package/test_import_boundaries.py tests/unit/loom/queue/test_queue_models.py tests/unit/loom/queue/test_scheduler.py tests/contracts/test_queue_records_contract.py tests/contracts/test_queue_repository_contract.py tests/integration/queue/test_sqlite_repository.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: model records first, SQLite repository second, package/contract/integration tests third.
- Tests to run with each slice: model and contract tests after record work; integration tests after repository work; package tests after public exports.
- Decisions the executor must not revisit: no service/client/controller, no adapter behavior, no authority resource mutation, no public scheduler plugin API.
- Conditions that require stopping for the manager: any need to change the queue-owned identity semantics, store queue state in authority, or add service/controller behavior to make the repository useful.

## Refinement And Review Budget Status

- Phase implementation refinement: unused
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed locally before implementation.
- Final phase execution plan: this file.
- Implementation summary: pending.
- Implementation validation: pending.
- Refinement summary: pending.
- Blocker-resolution summary: pending.
- PR preparation: pending.
- Stack maintenance: none yet.
- Remaining blockers: none.
