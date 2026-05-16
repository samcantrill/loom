## Summary

@samcantrill

This PR implements Stage 19 Phase 4 by adding capability-aware reliability
timeout diagnostics and outcome persistence. It introduces explicit timeout
support and outcome vocabulary, extends executor descriptors with timeout
support metadata, and records timeout outcome facts when a stage attempt runs
with selected timeout policy.

Subprocess execution now enforces `runtime.reliability.timeout.duration_seconds`
at the worker subprocess boundary and returns a structured timeout failure when
the process exceeds the deadline. Local in-process execution remains
intentionally unsupported for safe interruption and records that unsupported
timeout outcome instead. Runtime/preflight capability diagnostics now report
unsupported retry, timeout support levels, and narrow lease capability gaps
without adding timeout fields to `ResourceRequest`.

## Acceptance Criteria

- [x] Timeout outcomes represent `enforced`, `delegated`, `observed`,
  `unsupported`, and `timed_out` facts.
- [x] Subprocess timeout policy is enforced and recorded as reliability
  metadata/outcomes.
- [x] Local in-process timeout enforcement remains unsupported and is recorded
  as an explicit reliability fact.
- [x] Runtime/preflight diagnostics surface retry deferral, timeout support,
  and resource-lease capability gaps.
- [x] Reliability timeout remains separate from resource admission waits and
  authority operational timeouts.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Focused Phase 4 pytest batch | Passed | `189 passed` across package, unit, contract, and integration coverage |
| `make validate-pr` | Passed | Ruff, Pyright, default suite `1800 passed, 26 skipped, 18 deselected`; config-extra `446 passed, 1837 deselected`; build succeeded |
| `make test-summary` | Passed | Overall `2274 passed, 18 skipped, 1853 deselected`; see suite table below |
| GitHub checks | Pending | To be populated by GitHub after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 102 | 0 | 0 | 1 | 0 | 103 | 15.30s | 19% |
| unit | passed | 1268 | 0 | 0 | 7 | 1 | 1275 | 63.07s | 76% |
| contract | passed | 256 | 0 | 0 | 2 | 0 | 258 | 12.81s | 58% |
| integration | passed | 159 | 0 | 0 | 8 | 13 | 167 | 58.95s | 63% |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 43 | 40.25s | 59% |
| config-extra | passed | 446 | 0 | 0 | 0 | 1837 | 446 | 93.94s | 62% |
| Overall | passed | 2274 | 0 | 0 | 18 | 1853 | 2292 | 284.31s | - |

## Assumptions And Risks

- Local in-process timeout enforcement is deliberately unsupported because
  interrupting arbitrary Python safely requires a different execution boundary.
- Delegated and observed timeout support is represented through the shared
  vocabulary and descriptor/test paths; concrete scheduler/container behavior
  remains adapter-specific future work.
- Retry automation remains out of scope for Phase 4 and is still assigned to
  Phase 5.
