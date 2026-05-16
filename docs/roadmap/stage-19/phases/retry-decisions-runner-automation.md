# Phase 5 Execution Plan: Retry Decisions And Runner-Owned Automation

## Metadata

- Status: scope-complete phase execution plan
- Feature focus: Reliability Policies And Transactions
- PR title: `Reliability Policies And Transactions - Phase 5: Retry Decisions And Runner Automation`
- PR: pending
- Branch: `codex/retry-decisions-runner-automation`
- Worktree: `/home/samcantrill/work/loom-worktrees/retry-decisions-runner-automation`
- Phase execution plan path: `docs/roadmap/stage-19/phases/retry-decisions-runner-automation.md`
- Full plan: `docs/roadmap/stage-19/implementation-plan.md`
- Source phase: Phase 5, `retry-decisions-runner-automation`
- Stack predecessor: none; Phases 1 through 4 are merged into `develop`
- Base branch: `develop` at `166e9c1` after Phase 4 merge metadata
- Target branch: `develop`
- Workflow path: expanded path
- Plan quality gate: passed on 2026-05-16 in the selected implementation plan
- Draft pass: completed by manager-local planning in this assignment
- Refine pass: completed by manager-local planning after reading runner,
  lifecycle, stage-attempt, reliability, and store contracts
- Blockers: none

## Objective

Implement conservative opt-in retry as runner-owned automation. Retry must be
driven by persisted reliability facts, never by executor-local loops. The
runner may schedule a next attempt only after it has persisted a retry decision
showing policy enabled, remaining total-attempt budget, retriable failure
classification, and transaction-safe prior attempt state.

## Current Source And Harness Findings

- `PipelineRunner._run_controller_stage_action` is the common controller path
  used by both serial execution and parallel task submission before returning a
  `StageRunResult`.
- `_run_stage` and `_run_prepared_worker_stage` allocate one attempt at a time
  through `next_stage_attempt`, write inputs/fingerprints, run the executor,
  and commit or persist failure facts.
- Phase 3 already writes `FailureClassification` into persisted failure
  details, and Phase 4 records timeout outcomes in executor metadata and
  timeout records.
- `RunReliabilityStore` already exposes `write_retry_decision`,
  `list_retry_decisions`, and stage-attempt transaction reads across local,
  SQLite, in-memory, and authority-backed serial stores.
- `RetryDecisionRecord` already records policy max attempts, attempt count,
  next attempt, decision reason, status detail, failure classification, and
  transaction ID.
- `StageAttemptTransactionState` gives enough safety evidence for a first
  conservative evaluator: attempts that reached `STAGED`, `COMMITTED`, or
  `COMMIT_FAILED` are not retried automatically.

## In-Scope Work

- Add execution-owned retry evaluation helpers that build and persist
  `RetryDecisionRecord` values from resolved runtime policy and recorded stage
  facts.
- Add runner-owned retry looping around one `RUN` stage action, covering local
  and prepared-worker/subprocess paths through the same controller method.
- Persist denied decisions for disabled policy, exhausted attempts,
  non-retriable failures, cancellation, unsafe transaction state, and missing
  persistence support where a decision can be written.
- Persist allowed decisions before scheduling the next attempt.
- Update retry capability diagnostics now that runner-owned retry decisions are
  implemented.
- Add targeted unit, contract, integration, and docs coverage.

## Out-of-Scope Work

- Advanced backoff, sleeps, jitter, cross-run retry budgets, retry windows, or
  resource-aware escalation.
- Executor-local retry loops or backend-specific retry policy keys.
- Retrying graph, config, validation, planning, or blocked-stage failures.
- Event-sink-triggered retry behavior or Stage 20 event grammar changes.
- Cleanup, deletion, retention, or rollback execution.

## Retry Decision Matrix

The evaluator records exactly one decision for each failed or cancelled attempt
that reaches the controller retry gate.

| Condition | Decision reason | Retry? | Notes |
| --- | --- | --- | --- |
| No resolved retry policy, disabled policy, or default disabled policy | `retry.disabled` | no | Defaults remain no-retry. |
| Attempt count is greater than or equal to `max_attempts` | `retry.max_attempts_exhausted` | no | `max_attempts` is total attempts including the current attempt. |
| Stage result is `CANCELLED` | `retry.cancelled` | no | Cancellation does not become a failure retry. |
| Failure classification is non-retriable | `retry.non_retriable_failure` | no | Preserves validation/contract/resource denial behavior. |
| No latest stage-attempt transaction can be found | `retry.transaction_missing` | no | Retry requires durable safety evidence. |
| Any transaction in the attempt chain is `STAGED`, `COMMITTED`, or `COMMIT_FAILED` | `retry.unsafe_transaction_state` | no | Conservative duplicate-output guard. |
| Latest transaction state is not `FAILED` | `retry.unsafe_transaction_state` | no | Avoids retry while state is ambiguous or still running. |
| All checks pass | `retry.allowed` | yes | `next_attempt` is current attempt + 1 and is persisted before action. |

`RetryDecisionRecord.attempt_count` records the current attempt number. Denied
decisions use `next_attempt: null`; allowed decisions use the next total attempt
number.

## Scope Contract

- `loom.pipeline.reliability` remains import-light. Store and runner inspection
  stays in `loom.pipeline.execution`.
- Executors continue to report one attempt result and do not inspect retry
  policy or schedule retries.
- The runner returns the final attempt result for a stage. Earlier failed
  attempts remain inspectable through failure, transaction, and retry-decision
  facts.
- Parallel execution may use the same per-stage retry wrapper, but Phase 5 does
  not add new scheduling policy beyond bounded attempts for the active stage.
- Retry decisions are plain durability facts and may be projected into Stage 20
  events later.

## Test Plan

### Package Suite

- Status: required
- Expected paths: `tests/package/test_pipeline_reliability_api.py`,
  `tests/package/test_import_boundaries.py`
- Required assertions or deferral reason: retry helpers do not break
  import-light reliability or runtime boundaries.

### Unit Suite

- Status: required
- Expected paths: `tests/unit/loom/pipeline/execution/test_runner.py`,
  `tests/unit/loom/pipeline/execution/test_lifecycle.py`,
  `tests/unit/loom/pipeline/reliability/test_reliability_models.py`,
  `tests/unit/loom/pipeline/test_executor_capabilities.py`
- Required assertions or deferral reason: evaluator records allowed and denied
  decisions; runner retries only after allowed persisted decisions; unsafe
  transaction states deny retry; retry diagnostics no longer claim Phase 5 is
  deferred.

### Contract Suite

- Status: required
- Expected paths: `tests/contracts/test_reliability_contract.py`,
  `tests/contracts/test_executor_contract.py`,
  `tests/contracts/test_executor_capabilities_contract.py`
- Required assertions or deferral reason: retry decision shape remains stable
  and executor contracts still expose one-attempt execution only.

### Integration Suite

- Status: required
- Expected paths:
  `tests/integration/pipeline/test_local_execution_failures.py`,
  `tests/integration/pipeline/test_local_execution.py`,
  `tests/integration/pipeline/test_subprocess_executor_integration.py`
- Required assertions or deferral reason: local and subprocess-style runner
  flows retry allowed failures and preserve existing no-policy behavior.

### E2E Suite

- Status: deferred
- Expected paths: none specific for Phase 5
- Required assertions or deferral reason: Phase 5 changes runner behavior and
  persisted reliability facts; final user-facing inspection is Phase 6 scope.

### Opt-In Suites

- Status: deferred
- Markers affected: no real cluster, container, cloud, network, service,
  telemetry, or optional-SDK markers
- Required assertions or deferral reason: fake/local/subprocess coverage is
  sufficient for runner-owned retry semantics.

## Validation Commands

Targeted development commands:

```sh
uv run pytest tests/package/test_pipeline_reliability_api.py tests/package/test_import_boundaries.py
uv run pytest tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/reliability/test_reliability_models.py tests/unit/loom/pipeline/test_executor_capabilities.py
uv run pytest tests/contracts/test_reliability_contract.py tests/contracts/test_executor_contract.py tests/contracts/test_executor_capabilities_contract.py
uv run pytest tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_subprocess_executor_integration.py
```

Final PR-preparation commands:

```sh
make validate-pr
make test-summary
```

## Design Impact

- Maintainability: retry decisions live in one execution-owned helper and the
  runner owns scheduling, keeping executors simple.
- Extensibility: future backoff, scheduler, or event projections can consume
  the same decision records without changing attempt execution contracts.
- Future compatibility: Stage 20 can project retry decisions and Stage 21 can
  reason about unsafe transaction denial without parsing logs.
- Domain neutrality: reasons are generic policy/transaction/failure categories.

## Alternatives Rejected

| Alternative | Reason rejected |
| --- | --- |
| Retry inside executors | Violates the Stage 19 runner/authority ownership decision and hides attempts from stores. |
| Retry without denied decision records | Leaves users unable to inspect why policy did not act. |
| Treat any failed attempt as retry-safe | Risks duplicate outputs after staged or commit-failed attempts. |
| Add backoff now | Roadmap explicitly defers advanced retry policy. |

## Debt Introduced

| Debt | Reason accepted | Revisit trigger |
| --- | --- | --- |
| No backoff or delay policy | Stage 19 public policy only supports bounded total attempts | Users need retry pacing after Stage 19 lands. |
| Unsafe transaction detection is conservative | Duplicate-output prevention is more important than automatic recovery | Later transaction records distinguish rollback/cleanup outcomes more precisely. |
| Cancellation retry uses synthetic denial classification | Existing retry decision schema is failure-classification-shaped | A future cancellation policy is introduced. |

## Reviewability

- Files and areas to inspect: `src/loom/pipeline/execution/reliability.py`,
  `src/loom/pipeline/execution/runner.py`,
  `src/loom/pipeline/stores/sqlite_authority.py`,
  `src/loom/pipeline/runtime/capabilities.py`, runner tests, reliability
  contract tests, authority retry allocation coverage, and docs.
- Scope-control checks: no executor-local retry loop, no backoff, no event
  sink behavior, no cleanup/deletion behavior, no resource-aware retry
  escalation.

## Refinement And Review Budget Status

- Phase implementation refinement: not needed; manager-local implementation
  iteration resolved targeted validation findings before PR preparation and no
  formal refiner pass was consumed
- PR review: unused; one automated review pass available
- Blocker resolution: 0/3 used

## Completion Notes

- Draft plan: completed in this artifact
- Final phase execution plan: completed in this artifact
- Implementation summary: added runner-owned retry evaluation and scheduling,
  persisted allowed and denied `RetryDecisionRecord` facts, kept executors
  one-attempt-at-a-time, allowed SQLite authority allocation after failed
  uncommitted attempts, merged config-authored runtime reliability options into
  runner execution, updated retry capability diagnostics, and documented
  conservative retry behavior.
- Implementation validation: targeted Ruff and Pyright passed for touched
  source/tests; targeted pytest passed with `184 passed` across package,
  unit, contract, and local/subprocess integration reliability suites.
  `make validate-pr` passed Ruff, Pyright, default tests
  (`1806 passed, 26 skipped, 18 deselected`), config-extra tests
  (`447 passed, 1843 deselected`), and package build. `make test-summary`
  passed package (`102 passed, 1 skipped`), unit (`1274 passed, 7 skipped,
  1 deselected`), contract (`256 passed, 2 skipped`), integration
  (`159 passed, 8 skipped, 13 deselected`), e2e (`43 passed, 2 deselected`),
  and config-extra (`447 passed, 1843 deselected`).
- Refinement summary: not needed as a separate formal pass; validation findings
  were addressed directly during implementation before commits.
- Blocker-resolution summary: not needed at plan time
- PR preparation: pending
- Merge summary: pending
- Stack maintenance: pending
- Remaining blockers: none
