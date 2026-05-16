# Phase 2 Execution Plan: Reliability Persistence And Read Models

## Metadata

- Status: refined phase execution plan
- Feature focus: Reliability Policies And Transactions
- PR title: `Reliability Policies And Transactions - Phase 2: Persistence And Read Models`
- Branch: `codex/reliability-persistence-read-models`
- Worktree: `/home/samcantrill/work/loom-worktrees/reliability-persistence-read-models`
- Phase execution plan path: `docs/roadmap/stage-19/phases/reliability-persistence-read-models.md`
- Full plan: `docs/roadmap/stage-19/implementation-plan.md`
- Source phase: Phase 2, `reliability-persistence-read-models`
- Stack predecessor: none; Phase 1 merged before implementation began
- Base branch: `develop` at `9ec336e` after Phase 1 merge metadata
- Target branch: `develop`
- Merge eligibility: root PR is eligible to merge into `develop` only after phase implementation, targeted validation, `make validate-pr`, `make test-summary`, automated review, and CI pass with no blockers
- Workflow path: expanded path
- Successor dependency notes: Phase 3 may stack on this branch only after Phase 2 is open or prepared, validated, and recorded by the manager; keep this branch while successors depend on it
- Plan quality gate: passed on 2026-05-16 in the selected implementation plan
- Plan quality gate loop budget: implementation-plan review, bounded refinement, and confirmation review are complete; no blocking findings remain
- Draft pass: completed by `loom_phase_planner` in this assignment
- Refine pass: completed by `loom_phase_planner` in this assignment
- Setup limitations: initial planning used `codex/reliability-contracts-runtime-policy` at `b1c1705`; after Phase 1 merged, the manager rebased the Phase 2 plan commit onto updated `origin/develop` at `9ec336e` and retargeted this phase to `develop` before implementation.
- Blockers: none

## Objective

Add authoritative store and read-model facets for Phase 1 reliability facts so status details, stage-attempt transactions, retry decisions, timeout outcomes, and selected policy facts can be written and read as versioned records. This phase establishes durable persistence and inspection data shapes only; it must not wire execution lifecycle writes, retry automation, timeout enforcement, diagnostics, CLI presentation, event emission, cleanup, deletion, or retention behavior.

## Full-Plan Context

Stage 19 implements reliability policies and transactions in six phases. Phase 1 added import-light reliability policy, record, and protocol contracts plus `runtime.reliability` parsing and merge semantics. Phase 2 makes those records durable and readable through store-owned facets. Phase 3 will write transaction and classification facts from execution. Phase 4 will record timeout outcomes and diagnostics. Phase 5 will evaluate and persist runner-owned retry decisions before retrying. Phase 6 will finalize user-facing inspection and docs. Stage 20 owns runtime events and event sinks; Stage 21 owns cleanup, deletion, retention, and run-collection GC.

## Stack Context

- Root or stacked phase: root phase after predecessor merge and rebase
- Current predecessor branch or PR: Phase 1 PR https://github.com/samcantrill/loom/pull/176 is merged into `develop`
- Why this base branch is correct: Phase 2 depends on the Phase 1 reliability contracts now present on `develop`
- Retarget/rebase plan after predecessor merge: complete before implementation; rerun validation before PR submission
- Branch cleanup constraints: do not delete this branch while Phase 3 or later successors target it

## Source Phase Summary

- Goal: add store/read-model facets for reliability facts without replacing existing authority records.
- Required scope: append/read surfaces for policy facts, `ReliabilityStatusDetail`, `StageAttemptTransaction`, `RetryDecisionRecord`, and `TimeoutOutcomeRecord`; versioned records keyed by run URI, stage identifier, attempt, transaction ID, timestamps, reason codes, and causal references; local and authority-compatible coverage.
- Required checkpoints: choose a concrete local materialization layout; keep facts out of `events.jsonl`, status metadata, and executor logs; preserve authority as the lifecycle source of truth; expose missing-record reads as empty/absent rather than failures.
- Acceptance criteria: reliability records write/read strictly; read models preserve association with existing stage attempts, output commits, leases, status records, materialized refs, and cleanup candidates; local, in-memory, SQLite, and service authority paths use the same typed contract where applicable; future Stage 20/21 can project from stable references.

## Current Source And Harness Findings

- Existing files or modules that constrain this phase: `src/loom/pipeline/reliability/_models.py` provides the Phase 1 record classes and `ReliabilityRecordStore`/`ReliabilityTransactionStore` protocols; `src/loom/pipeline/stores/read_models.py` owns authoritative read-model value records; `src/loom/pipeline/stores/authority.py` owns `PerRunAuthorityStore`; `src/loom/pipeline/stores/local_runs.py` owns local materialization; `src/loom/pipeline/stores/sqlite_authority.py`, `service_authority.py`, and `tests/support/authority_stores.py` provide authority-compatible implementations.
- Existing tests or harness behavior: authority model tests check strict `to_dict`/`from_dict`; authoritative read-model contracts exercise in-memory and service stores; SQLite authority tests lock revisioned snapshots, stage attempts, leases, output commits, cleanup candidates, and audit sequence behavior; reliability contract tests already prove Phase 1 records are stable plain data.
- Import-boundary or dependency constraints: stores may import `loom.pipeline.reliability`; `loom.pipeline.reliability` must remain import-light and must not import stores, authority, execution, diagnostics, CLI, plugins, or optional backends.
- Vocabulary constraints: use `RunStore` and `StageStore` for public authority lifecycle APIs, `LocalRunStore` only for local filesystem materialization, and `authoritative read model` for backend-neutral snapshots.

## In-Scope Work

- Add store-owned reliability read-model records or facets in `src/loom/pipeline/stores/`, reusing Phase 1 `ReliabilityPolicy`, `ReliabilityStatusDetail`, `StageAttemptTransaction`, `RetryDecisionRecord`, and `TimeoutOutcomeRecord`.
- Add write/read methods or narrowly named facets for reliability policy facts, status details, transactions, retry decisions, and timeout outcomes.
- Extend local materialization with a concrete reliability facts layout under the run directory, using strict per-record JSON documents and existing path validation/atomic-write patterns.
- Extend authority-compatible stores so in-memory, SQLite, and service-backed test paths can write and read the same reliability facts.
- Extend authoritative read models with typed reliability projections and empty tuple/default behavior for older or missing reliability records.
- Preserve existing lifecycle truth: stage attempts, output commits, leases, status transitions, materialized refs, recovery records, and cleanup candidates remain authoritative records; reliability facts reference them.
- Add tests proving reliability facts are independent of `events.jsonl`, status metadata, and executor logs.
- Add targeted docs or docstrings only where needed to explain source-of-truth and local materialization behavior.

## Out-of-Scope Work

- Execution lifecycle writes for transaction/status-detail facts.
- Failure classifier integration, commit-failure classification, cancellation/interruption handling, or status enum changes.
- Runner retry automation, next-attempt scheduling, retry evaluator behavior, retry backoff, cross-run retry budgets, or resource-aware retry escalation.
- Timeout enforcement, subprocess timeout behavior, scheduler/container timeout handling, or preflight diagnostics.
- Broad CLI commands or user-facing status/logs presentation.
- Runtime event grammar, event sinks, audit-event projection, callback failure policy, plugin-discovered sinks, notifications, telemetry, or service integrations.
- Cleanup execution, physical deletion, retention enforcement, or run-collection GC.
- Heavy optional dependencies, network/service requirements, real cluster/container validation, or broad source-tree refactors.

## Assumptions

- Phase 1 reliability contracts are the source record shapes for this phase; store read models may add envelopes or projections but must not change the contract semantics.
- Phase 1 uses `stage_id`; Phase 2 should map that value to the existing store `stage_name` concept and must not introduce a second independent stage identity.
- Reliability facts can be written in tests without Phase 3 execution hooks; Phase 3 will later decide when lifecycle code writes them.
- Missing reliability facts are normal for runs created before Phase 2 or before later phases write facts.
- Existing authority schema policy should fail loudly for malformed or unsupported authority state; Phase 2 should not add migration machinery beyond the existing schema-check pattern.

## Scope Contract

Public behavior:

- Reliability write methods validate typed Phase 1 records and obvious run URI mismatches. They must not parse executor logs, status metadata, or `events.jsonl`.
- Reliability reads return typed records ordered deterministically by existing identity/order fields: policy scope, status creation time, transaction causal chain, retry decision identity, and timeout outcome identity. Missing families return `None` or empty tuples according to local store conventions.
- ID-bearing facts are immutable after first write. Rewriting the same ID with identical payload may be idempotent; rewriting the same ID with a different payload must fail instead of silently replacing history.
- `ReliabilityStatusDetail.stage_id` is treated as the store `stage_name` for Stage 19. Do not create a new public stage-id namespace in stores.
- Read-model projections may join reliability facts to `StageAttempt`, `OutputCommitRecord`, `LeaseRecord`, status, materialized refs, and cleanup candidates when references match. They must not require Phase 3 lifecycle writes before manual store tests can persist facts.
- `AuthoritativeRunSnapshot` and stage snapshots may gain typed reliability projection fields, but deserialization must accept older snapshots with missing reliability fields and default them to empty facts.

Module boundaries:

- `src/loom/pipeline/stores/read_models.py` owns store/read-model value records.
- Store implementations under `src/loom/pipeline/stores/` own persistence and authority-compatible behavior.
- `loom.pipeline.reliability` remains the import-light contract package and must not import store modules.
- Execution, diagnostics, CLI, event, and cleanup modules are readers or future writers only in later phases.

Local materialization:

- Use a run-scoped reliability facts directory under the local run directory, with family subdirectories for policy facts, status details, transactions, retry decisions, and timeout outcomes.
- Store strict JSON documents with schema/version information from Phase 1 records and any minimal store envelope needed for policy scope or local filename identity.
- Use existing `LocalRunStore` validation, `atomic_write_json`, corrupt-document errors, and freshness touching patterns. Do not use `events.jsonl`, status files, failure payloads, or executor logs as reliability fact storage.

Authority compatibility:

- Add the same reliability fact semantics to in-memory, SQLite, and service authority paths.
- SQLite authority should use dedicated reliability tables or an equivalent normalized record store with schema checks that fail clearly on missing/corrupt state.
- Service authority wire payloads must remain plain data and round trip through the existing authority protocol/mutation-service patterns if those paths are touched.

## Design Impact

- Maintainability: reliability facts become a store-owned surface beside existing lifecycle facts instead of being inferred by execution code or logs.
- Extensibility: Stage 20 event projection, Stage 21 cleanup planning, future remote stores, and future diagnostics can consume typed facts through stable read models.
- Domain neutrality: records remain generic to pipeline runs, stages, attempts, failures, timeouts, and transactions; no service-specific or research-domain fields are added.
- Source-tree boundaries: stores depend on reliability contracts; reliability contracts do not depend on stores; execution, diagnostics, CLI, events, and cleanup stay outside the Phase 2 write scope.

## Future Compatibility

- Phase 3 can write transaction/status-detail facts through the Phase 2 facets without changing read-model shape.
- Phase 4 can persist timeout outcomes through the same store surface without adding timeout resource fields.
- Phase 5 can persist allowed and denied retry decisions before runner retry actions.
- Phase 6 can expose read-only inspection from the authoritative read model without parsing backend logs.
- Stage 20 can project events from committed reliability facts because identities, timestamps, run/stage/attempt references, transaction IDs, reason codes, and causal links are preserved.
- Stage 21 can consume transaction and cleanup-candidate associations without Phase 2 performing deletion or retention.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Store reliability facts in `events.jsonl` | Stage 20 owns event grammar; Stage 19 facts must be store/read-model records, not event-log projections. |
| Embed reliability facts in status metadata | Status metadata is not the authority-compatible fact layer and would blur stable status with explanatory reliability records. |
| Infer retry/timeout/transaction facts from executor logs | Logs are backend-specific and not a durable typed source of truth. |
| Replace existing `StageAttempt`, lease, output commit, or cleanup records | Phase 2 should associate reliability facts with authority records, not replace lifecycle truth. |
| Add execution hooks in the persistence phase | Lifecycle writes and retry/timeout behavior belong to later phases and would make this PR too broad to review. |
| Add a new global cleanup or lease model | Cleanup/deletion is Stage 21, and Phase 4 will handle only narrow lease compatibility diagnostics if needed. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No intentional Phase 2 debt planned | This phase is the persistence/read-model foundation and should produce the durable layout rather than defer it | Any reliability fact family cannot be represented in local and authority-compatible stores without broad store redesign. |
| Policy facts may need a store envelope around `ReliabilityPolicy` | Phase 1 intentionally made policy a config/contract model, not a run-scoped fact record | The executor cannot persist selected run/stage policy facts without adding ambiguous wrapper fields or changing Phase 1 semantics. |
| No migration machinery for older authority state | Existing authority schema policy is loud-fail; migrations are outside this phase unless already required by local patterns | Phase 2 creates a schema change that cannot be detected or reported clearly by `check_schema`. |

## Reviewability

- Expected PR size and shape: a focused store/read-model PR touching reliability store facets, local materialization, authority-compatible implementations, exports, and tests. It should not include execution, diagnostics, CLI, event, or cleanup behavior.
- Files and areas to inspect: `src/loom/pipeline/stores/read_models.py`, `src/loom/pipeline/stores/authority.py`, `src/loom/pipeline/stores/local_runs.py`, `src/loom/pipeline/stores/sqlite_authority.py`, `src/loom/pipeline/stores/service_authority.py`, `tests/support/authority_stores.py`, store facade exports, and targeted package/unit/contract/integration tests.
- Scope-control checks: no runner retry loop, no timeout enforcement, no execution lifecycle write hooks, no CLI output, no event sink or event grammar, no cleanup/deletion behavior, no optional dependencies, and no imports from stores back into `loom.pipeline.reliability`.

## Implementation Steps

1. Add reliability store/read-model records or facets and public exports that reuse Phase 1 record classes while preserving import boundaries.
2. Implement local `LocalRunStore` reliability fact paths, strict JSON read/write helpers, deterministic list/read behavior, corrupt-document handling, and freshness touching.
3. Add authority-compatible persistence for in-memory, SQLite, and service store paths, including schema checks and plain-data wire round trips where relevant.
4. Extend authoritative snapshots/read-model helpers with typed reliability projections and backward-compatible empty defaults.
5. Add targeted tests for strict serialization, idempotent/conflicting writes, missing/corrupt records, association with existing authority facts, and independence from events/status/logs.
6. Add minimal docs or docstrings explaining local materialization and source-of-truth boundaries, then leave full CLI/docs finalization to Phase 6.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_import_boundaries.py`, `tests/package/test_pipeline_store_api.py`, and `tests/package/test_pipeline_reliability_api.py` if facade behavior changes
- Required assertions or deferral reason: store exports expose reliability facets without making root or reliability imports heavy; `loom.pipeline.reliability` still does not import stores, execution, executors, diagnostics, CLI, authority service clients, plugins, or optional backends.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/stores/test_authority_models.py`, `tests/unit/loom/pipeline/stores/test_local_runs.py`, `tests/unit/loom/pipeline/stores/test_sqlite_authority.py`, new focused store reliability tests under `tests/unit/loom/pipeline/stores/`, and `tests/unit/loom/pipeline/reliability/test_reliability_models.py` only for regression coverage if Phase 1 contracts are touched
- Required assertions or deferral reason: reliability read-model records serialize strictly; local fact writes/readbacks round trip typed records; missing facts read as empty; corrupt documents fail clearly; duplicate identical writes are idempotent or rejected consistently; duplicate IDs with different payload fail; SQLite snapshots include reliability facts and preserve revisions/schema checks.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_reliability_contract.py`, `tests/contracts/test_store_contract.py`, `tests/contracts/test_run_store_authority_contract.py`, `tests/contracts/test_authoritative_read_model_contract.py`, and a new reliability store contract test if the implementation adds a distinct facet
- Required assertions or deferral reason: local/in-memory/service/SQLite paths expose the same reliability fact semantics; authoritative read models carry reliability facts as typed plain data; older snapshots without reliability fields remain accepted; facts are not sourced from `events.jsonl`, status metadata, or executor logs.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_stores.py`, `tests/integration/pipeline/test_materialization_read_models.py`, `tests/integration/pipeline/test_local_execution_failures.py`, and `tests/integration/pipeline/test_sqlite_authority_backend.py` if SQLite authority behavior changes
- Required assertions or deferral reason: local store and authoritative read-model paths can persist/read reliability facts alongside existing lifecycle records without changing current local execution failure behavior. No new execution writes are required in this phase.

### E2E Suite

- Status: deferred
- Expected paths: none for Phase 2
- Required assertions or deferral reason: Phase 2 has no CLI output, runner behavior, timeout enforcement, retry automation, or user workflow change. E2E coverage belongs to Phase 6 if read-only CLI inspection is added.

### Opt-In Suites

- Status: deferred
- Markers affected: no real cluster, container, cloud, network, service, telemetry, or optional-SDK markers
- Required assertions or deferral reason: persistence/read-model behavior must be proven with default fake/local/in-memory/service fixtures only. Real SLURM/container/cloud validation is outside Phase 2.

## Risks

- Store schema changes could silently diverge between local, SQLite, service, and in-memory authority paths.
- Extending authoritative snapshots could break older plain-data snapshots unless missing reliability fields default cleanly.
- Reliability facts could accidentally duplicate or override lifecycle truth instead of referencing it.
- A broad read-model change could drift into Phase 6 presentation work.
- Policy fact persistence could become ambiguous if it tries to reinterpret authored config instead of storing selected/resolved policy facts.
- Import facade edits could pull stores into `loom.pipeline.reliability` or make package imports heavy.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_import_boundaries.py tests/package/test_pipeline_store_api.py tests/package/test_pipeline_reliability_api.py
uv run pytest tests/unit/loom/pipeline/stores tests/unit/loom/pipeline/reliability/test_reliability_models.py
uv run pytest tests/contracts/test_reliability_contract.py tests/contracts/test_store_contract.py tests/contracts/test_run_store_authority_contract.py tests/contracts/test_authoritative_read_model_contract.py
uv run pytest tests/integration/pipeline/test_local_stores.py tests/integration/pipeline/test_materialization_read_models.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_sqlite_authority_backend.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Handoff Notes For `loom_phase_executor`

- Safe implementation slices: start with read-model/store facet types and exports, then local materialization, then in-memory/service authority compatibility, then SQLite authority/schema checks, then authoritative snapshot projection and tests.
- Tests to run with each slice: package/import-boundary tests after exports; unit store tests after local materialization; authority contract tests after in-memory/service facets; SQLite unit/integration tests after SQLite tables/schema; authoritative read-model contracts after snapshot projection.
- Decisions the executor must not revisit: use Phase 1 reliability record classes; map `stage_id` to existing `stage_name`; keep facts out of events/status/logs; keep reliability facts immutable by ID; preserve missing-record empty defaults; keep execution hooks, retry automation, timeout enforcement, diagnostics, CLI, events, and cleanup out of scope.
- Conditions that require stopping for the manager: persistence requires changing Phase 1 public record semantics; `loom.pipeline.reliability` would need to import stores; existing authority records must be replaced rather than referenced; SQLite/service schema compatibility cannot be detected clearly; or implementation needs execution lifecycle writes to prove store behavior.

## Refinement And Review Budget Status

- Phase implementation refinement: unused; targeted validation passed after
  manager-local implementation cleanup, so no separate refinement pass has
  been consumed.
- PR review: unused
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: completed in this artifact
- Implementation summary: complete. Added typed reliability policy facts,
  status details, stage-attempt transactions, retry decisions, and timeout
  outcomes to store read models; added local run-store JSON materialization
  under run-scoped `reliability/` family directories; added in-memory, SQLite,
  and service authority-compatible persistence/readback; added store facade
  exports and backend capability signaling; preserved backward-compatible empty
  defaults in authoritative snapshots and completed-run bundle metadata.
- Implementation validation: targeted Ruff and Pyright passed for the touched
  store, adapter, support, and test paths. Targeted pytest evidence passed:
  `91 passed` for package/store unit/contract coverage,
  `8 passed` for authoritative read-model contracts,
  `229 passed` for store/authority contract coverage,
  `9 passed, 1 skipped` for phase integration coverage,
  `67 passed` for package/import/reliability API coverage, and
  `26 passed` for reliability/store/authority contract coverage. Final
  `make validate-pr` and `make test-summary` remain required before PR
  opening.
- Refinement summary: not needed so far; no targeted validation blocker
  remains after local implementation cleanup.
- Blocker-resolution summary: pending
- PR preparation: pending
- Stack maintenance: pending
- Remaining blockers: none
