## Summary

@samcantrill

This PR implements Stage 19 Phase 5 by adding conservative, runner-owned retry
automation backed by persisted reliability facts. The runner now evaluates retry
policy after failed or cancelled stage attempts, writes a `RetryDecisionRecord`,
and schedules another attempt only after an allowed decision has been persisted.
Executors still execute one attempt at a time and do not own high-level retry
policy.

The retry gate records durable denial reasons for disabled policy, exhausted
attempt budgets, cancellation, non-retriable failure classifications, missing
transaction evidence, and unsafe output transaction state. It only allows retry
when policy is enabled, `max_attempts` has remaining total-attempt budget, the
failure classification is retriable, and the latest transaction chain proves the
attempt failed before staging or committing outputs.

The implementation also updates runtime/preflight diagnostics so enabled retry
is reported as runner-owned behavior, allows SQLite authority allocation after a
failed uncommitted stage attempt, and documents the current
`runtime.reliability.retry` semantics.

## Acceptance Criteria

- [x] Retry is disabled by default and opt-in through
  `runtime.reliability.retry`.
- [x] Allowed and denied retry decisions are persisted before any next attempt.
- [x] `max_attempts` is enforced as a total-attempt budget including the first
  attempt.
- [x] Cancellation, non-retriable failures, missing transaction evidence, and
  unsafe output transaction states do not retry.
- [x] Executors remain one-attempt execution surfaces with no executor-local
  retry loops.
- [x] Runtime/preflight diagnostics describe retry as runner-owned behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 5 pytest batch | Passed | `184 passed` across package, unit, contract, and local/subprocess integration reliability coverage |
| `make validate-pr` | Passed | Ruff, Pyright, default suite `1806 passed, 26 skipped, 18 deselected`; config-extra `447 passed, 1843 deselected`; build succeeded |
| `make test-summary` | Passed | Overall `2281 passed, 18 skipped, 1859 deselected`; see suite table below |
| GitHub checks | Pending | To be populated by GitHub after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 102 | 0 | 0 | 1 | 0 | 103 | 15.28s | 19% |
| unit | passed | 1274 | 0 | 0 | 7 | 1 | 1281 | 66.27s | 76% |
| contract | passed | 256 | 0 | 0 | 2 | 0 | 258 | 12.70s | 58% |
| integration | passed | 159 | 0 | 0 | 8 | 13 | 167 | 59.31s | 63% |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 43 | 40.86s | 59% |
| config-extra | passed | 447 | 0 | 0 | 0 | 1843 | 447 | 96.29s | 63% |
| Overall | passed | 2281 | 0 | 0 | 18 | 1859 | 2299 | 290.70s | - |

## Assumptions And Risks

- Retry remains deliberately conservative. Attempts that reached staged,
  committed, or commit-failed output transaction state are denied to avoid
  duplicate authoritative outputs.
- Current retry policy has no backoff, delay, retry window, cross-run budget, or
  resource-aware escalation. Those remain future roadmap work.
- Cancellation is recorded as a retry denial rather than being converted into a
  failure retry path.
