# Phase 3 Execution Plan: Transaction And Failure Classification Integration

## Metadata

- Status: scope-complete phase execution plan
- Feature focus: Reliability Policies And Transactions
- PR title: `Reliability Policies And Transactions - Phase 3: Transaction And Failure Classification`
- PR: https://github.com/samcantrill/loom/pull/178
- Branch: `codex/transaction-failure-classification`
- Worktree: `/home/samcantrill/work/loom-worktrees/transaction-failure-classification`
- Phase execution plan path: `docs/roadmap/stage-19/phases/transaction-failure-classification.md`
- Full plan: `docs/roadmap/stage-19/implementation-plan.md`
- Source phase: Phase 3, `transaction-failure-classification`
- Stack predecessor: none; Phases 1 and 2 are merged into `develop`
- Base branch: `develop` at `8fa12d5` after Phase 2 merge metadata
- Target branch: `develop`
- Merge eligibility: root PR is eligible to merge into `develop` only after implementation, targeted validation, `make validate-pr`, `make test-summary`, automated review, and CI pass with no blockers
- Workflow path: expanded path
- Successor dependency notes: Phase 4 may stack on this branch only after Phase 3 is open or prepared, validated, and recorded by the manager; keep this branch while successors depend on it
- Plan quality gate: passed on 2026-05-16 in the selected implementation plan
- Draft pass: completed by manager-local planning in this assignment
- Refine pass: completed by manager-local planning in this assignment after reading execution, continuation, store, and reliability contract code
- Blockers: none

## Objective

Record reliability status-detail and transaction facts around stage attempts and add execution-owned failure classification helpers without changing `RunStatus` or `StageStatus`. This phase makes success, failure, cancellation, output staging, output commit, and commit-failure ordering inspectable from store facts. It must not add retry automation, timeout enforcement, diagnostics, CLI presentation, event emission, cleanup execution, deletion, or retention behavior.

## Full-Plan Context

Stage 19 implements reliability policies and transactions in six phases. Phase 1 added import-light reliability policy, record, and protocol contracts plus runtime parsing. Phase 2 added persistence/read-model facets for reliability facts. Phase 3 wires execution lifecycle facts and default failure classification. Phase 4 owns timeout outcomes and diagnostics. Phase 5 owns retry decisions and runner-owned retry. Phase 6 owns final inspection and docs.

## Source Phase Summary

- Goal: record transaction/status-detail facts around stage attempts and classify failures without changing status enums.
- Required scope: transaction begin/prepared/running/staged/commit/failure/cleanup-outcome recording around stage attempt lifecycle; default failure classifier over `ExecutionFailure`, exit code, signal, cancellation, executor metadata, store commit failures, timeout outcomes when available, and plain detail; status detail persistence before final failed status where applicable; commit failure behavior that does not mark partial outputs authoritative.
- Required checkpoints: define final transaction state names and causal ordering before implementation; preserve current status serialization; prove commit failures and ambiguous outputs are not authoritative.
- Acceptance criteria: success, failure, cancellation, commit failure, and cleanup-outcome facts are recorded in order and inspectable; status enums stay stable; transaction records include causal links for Stage 20/21.

## Current Source And Harness Findings

- `src/loom/pipeline/execution/lifecycle.py` centralizes status writes for run, stage, commit, failure, cancellation, skipped, and blocked behavior.
- `commit_stage_execution_result` is the shared parent-side and stage-job commit path; output validation and output-commit failures flow through existing failure handling.
- `src/loom/pipeline/execution/runner.py` and `continuation.py` catch lifecycle/commit exceptions and map them to `ExecutionFailure.failure_type`.
- `src/loom/pipeline/execution/stage_attempts.py` prepares durable worker attempts and writes PENDING stage status before worker execution.
- `AuthorityBackedSerialRunStore` is the active local+authority execution adapter but currently needs run-store reliability delegation methods for lifecycle writers to persist facts into both local and authority-compatible stores.
- Phase 2 reliability persistence exists on `LocalRunStore`, `PerRunAuthorityStore` implementations, read models, and service/in-memory/SQLite authority paths.
- `StageAttemptTransaction` currently records transaction identity, run/stage/attempt, status detail, and causal parent, but not a first-class transition state. Phase 3 should add a backward-compatible state field rather than relying on transaction-id parsing.

## In-Scope Work

- Add a small import-light `StageAttemptTransactionState` enum and optional/backward-compatible `state` field to `StageAttemptTransaction`.
- Add execution-owned helpers for reliability status detail creation, failure classification, transaction IDs, causal parent selection, and atomic-ish status-detail plus transaction writes.
- Add reliability delegation methods to `AuthorityBackedSerialRunStore` so serial execution writes local materialization and authority-compatible reliability facts.
- Wire transaction/status-detail writes around prepared, running, staged, committed, failed, cancelled, and commit-failed lifecycle points where those states already exist.
- Add default failure classification over `ExecutionFailure` with conservative `retriable` flags and plain details copied from executor/failure metadata.
- Preserve failure classification facts in existing durable stage failure payload details so Phase 5 can consume classification without adding a new Phase 3 store family.
- Add tests proving status enums stay unchanged, reliability status details and transactions are written in order, commit failures leave no authoritative outputs, and cancellation/failure paths record inspectable facts.

## Out-of-Scope Work

- Automatic retry, retry evaluation, retry decision persistence, or next-attempt scheduling.
- Timeout enforcement, timeout capability diagnostics, or timeout outcome generation.
- CLI, diagnostics, event grammar, event sinks, telemetry, notifications, or plugin behavior.
- Cleanup execution, deletion, retention enforcement, or run-collection GC.
- Broad executor rewrites, resource-aware retry, backoff, cross-run budgets, or scheduler-health orchestration.

## Transaction State And Causal Ordering

Final Phase 3 state names:

| State | Stage status detail | Recorded when |
| --- | --- | --- |
| `prepared` | `PENDING` | A durable worker attempt is prepared before worker execution. |
| `running` | `RUNNING` | A stage attempt starts executing in parent-side or stage-job flow. |
| `staged` | `RUNNING` | Outputs have passed validation and are about to be written/committed. |
| `committed` | `SUCCEEDED` | Outputs are committed and final success status is written. |
| `failed` | `FAILED` | A failed attempt is persisted before final failed stage status where possible. |
| `cancelled` | `CANCELLED` | A cancellation/early-stop stage result is persisted. |
| `commit_failed` | `FAILED` | A store/output commit failure is classified and persisted without marking outputs authoritative. |

Causal ordering:

- For each run/stage/attempt, each newly written transaction points to the latest existing transaction for that same stage attempt as `causal_parent_id`.
- Transaction IDs are deterministic for one status-detail/state timestamp, using run URI, stage name, attempt, state, and timestamp. Rewriting the same fact is idempotent through the Phase 2 immutable store behavior.
- `staged` precedes `committed` or `commit_failed` when the shared commit path reaches output validation.
- `failed` and `cancelled` are terminal for Phase 3 and do not schedule retry.
- Cleanup outcome records remain Phase 4/Stage 21-adjacent work unless an existing cleanup candidate is already emitted by the output commit path.

## Scope Contract

Public behavior:

- Stage attempt reliability facts are optional for older runs and present for Phase 3 lifecycle paths.
- `RunStatus` and `StageStatus` values are unchanged.
- Reliability facts are written through store/read-model facets, not event logs, status metadata, or executor-log parsing.
- Failure classification is generic and conservative. Validation, graph/config, target construction, cancellation, resource admission, and store commit ambiguity are non-retryable by default; executor/stage runtime failures may be marked retriable as classifier input only, with Phase 5 still responsible for policy and transaction-safety decisions.
- Commit failures must record `commit_failed` or `failed` facts and must not create authoritative output commits or artifact facts.

Module boundaries:

- `loom.pipeline.reliability` remains import-light and does not import execution or stores.
- `loom.pipeline.execution` owns lifecycle helper integration and may import reliability contracts and store protocols.
- Stores remain persistence owners and do not import execution, CLI, diagnostics, or event modules.

## Design Impact

- Maintainability: lifecycle writes become explicit helpers rather than duplicated ad hoc status metadata.
- Extensibility: Phase 5 retry evaluation can consume stable classification and transaction facts without inferring from logs.
- Future compatibility: Stage 20 can project ordered transaction facts; Stage 21 can reason about commit-failure and cleanup-relevant facts without Phase 3 deleting data.
- Domain neutrality: failure reason codes remain generic runtime categories based on current `ExecutionFailure` vocabulary.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Encode transaction state only in `transaction_id` | It would make future inspection/event projection parse opaque identifiers and would not satisfy the explicit state-name checkpoint. |
| Store classification only in status metadata | The plan explicitly keeps reliability facts out of status metadata; stage failure payload details are already durable failure facts and are less coupled to stable status records. |
| Add a new classification store family in this phase | Phase 2 did not establish one, and Phase 5 can consume embedded classification facts from failures/decisions without broadening Phase 3 store schema. |
| Treat output commits as the full transaction history | Retry safety needs pre-commit and commit-failure states, not just successful commits. |
| Add cleanup/deletion behavior for rollback | Stage 21 owns physical cleanup, deletion, retention, and GC. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| Failure classification is embedded in durable stage failure details rather than a standalone classification store family | Phase 2 did not create a classification family, and Phase 3 should avoid another persistence surface unless Phase 5 proves it is needed | Phase 5 retry decisions cannot consume classification facts reliably from failure payloads or retry decision records. |
| Transaction state is added backward-compatibly with a default for older records | Existing Phase 2 records/tests may omit state; strict required migration is unnecessary before Stage 19 is complete | Phase 6 inspection needs to distinguish older unspecified records from Phase 3 records. |

## Reviewability

- Expected PR size and shape: focused reliability contract extension, execution lifecycle helpers, serial authority adapter delegation, and execution/store tests.
- Files and areas to inspect: `src/loom/pipeline/reliability/_models.py`, `src/loom/pipeline/execution/lifecycle.py`, any new execution reliability helper, `src/loom/pipeline/execution/runner.py`, `src/loom/pipeline/execution/continuation.py`, `src/loom/pipeline/execution/authority_adapter.py`, and targeted execution/integration tests.
- Scope-control checks: no retry loop, no timeout enforcement, no CLI/diagnostics/events, no cleanup deletion/retention, no status enum changes, no optional dependencies.

## Implementation Steps

1. Add `StageAttemptTransactionState` and a backward-compatible `state` field to `StageAttemptTransaction`, then update exports and serialization tests.
2. Add execution reliability helpers for status-detail records, default failure classification, transaction ID/cause handling, and store writes.
3. Add `AuthorityBackedSerialRunStore` reliability delegation methods to write/list/read local and authority reliability facts consistently.
4. Wire lifecycle helpers into `prepare_stage_attempt`, `write_stage_running`, `commit_stage_execution_result`, `persist_stage_failure`, and `persist_stage_cancellation`; add staged/committed/commit-failed facts around output validation/commit.
5. Preserve classification in stage failure payload details and add focused unit/integration assertions.
6. Update phase artifacts and run targeted validation, `make validate-pr`, and `make test-summary`.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_reliability_api.py`, `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: new transaction state enum exports without importing execution/stores into reliability.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/reliability/test_reliability_models.py`, `tests/unit/loom/pipeline/execution/test_lifecycle.py`, `tests/unit/loom/pipeline/execution/test_runner.py`, `tests/unit/loom/pipeline/execution/test_stage_attempts.py`, `tests/unit/loom/pipeline/execution/test_stage_job.py`, `tests/unit/loom/pipeline/execution/test_authority_adapter.py`
- Required assertions or deferral reason: transaction state round trips; lifecycle writes status-detail/transaction facts in order; default classifier maps current failure types; authority-backed commit failure records reliability facts and no authoritative outputs.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_reliability_contract.py`, `tests/contracts/test_authoritative_read_model_contract.py`, `tests/contracts/test_run_store_authority_contract.py`
- Required assertions or deferral reason: read models carry stateful transaction facts and older records remain compatible.

### Integration Suite

- Status: required
- Expected paths: `tests/integration/pipeline/test_local_execution_failures.py`, `tests/integration/pipeline/test_local_execution.py`, `tests/integration/pipeline/test_subprocess_executor_integration.py`
- Required assertions or deferral reason: local/authority-backed execution failure, success, and commit-failure flows persist reliability facts without changing current status behavior.

### E2E Suite

- Status: deferred
- Expected paths: none specific for Phase 3
- Required assertions or deferral reason: Phase 3 has no CLI or user workflow change beyond persisted facts; final user-facing inspection belongs to Phase 6.

### Opt-In Suites

- Status: deferred
- Markers affected: no real cluster, container, cloud, network, service, telemetry, or optional-SDK markers
- Required assertions or deferral reason: fake/local/default tests are sufficient for transaction/classification lifecycle behavior.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_reliability_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/reliability/test_reliability_models.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_stage_attempts.py tests/unit/loom/pipeline/execution/test_stage_job.py tests/unit/loom/pipeline/execution/test_authority_adapter.py
uv run pytest tests/contracts/test_reliability_contract.py tests/contracts/test_authoritative_read_model_contract.py tests/contracts/test_run_store_authority_contract.py
uv run pytest tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Refinement And Review Budget Status

- Phase implementation refinement: unused; implementation-pass fixes resolved timestamp-key and causal-parent ordering issues found by targeted validation
- PR review: used by manager-local automated review; no blocking findings
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: completed in this artifact
- Implementation summary: complete. Added stateful reliability transactions, execution-owned classification helpers, lifecycle transition writes, authority-backed serial-store delegation, status-detail key hardening for same-timestamp transitions, and focused package/unit/contract/integration coverage.
- Implementation validation: complete. Targeted reliability/execution tests passed (`94 passed, 1 skipped`), phase-required unit/store tests passed (`335 passed`), phase-required integration command passed (`4 passed, 2 skipped`), `make validate-pr` passed Ruff, Pyright, default suite (`1791 passed, 26 skipped, 18 deselected`), config-extra suite (`446 passed, 1828 deselected`), and build, and `make test-summary` passed all suite groups.
- Refinement summary: no separate implementation-refiner pass used.
- Blocker-resolution summary: not needed
- PR preparation: opened https://github.com/samcantrill/loom/pull/178 against `develop`; target verified with `gh pr view 178 --json baseRefName,headRefName,state,url`
- Merge summary: merged into `develop` at
  `b78d6d588b7e634e8d31ef02eccc7a101587b547` after
  `gh pr view 178 --json baseRefName,headRefName,state,url,mergeCommit,statusCheckRollup`
  confirmed target `develop`, open state, and successful CI
- Stack maintenance: no successor branch depends on this phase branch
- Remaining blockers: none
