## Summary

@samcantrill

This PR implements Stage 19 Phase 1 by adding the import-light reliability
contract surface and public runtime policy path. It introduces retry and
timeout policy models, reliability status/detail records, transaction, retry
decision, timeout outcome, classifier/evaluator/store/controller protocols,
and runtime merge helpers without adding persistence, execution automation,
diagnostics, CLI output, events, or cleanup behavior.

Runtime options now accept `runtime.reliability` and
`runtime.stage_options.<stage>.reliability`, including strict unknown-field
rejection, omitted-versus-explicit-disabled policy semantics, and
`max_attempts` as total attempts including the initial attempt. Legacy
top-level `retry`, `timeout`, and `timeout_seconds` remain rejected outside the
new reliability path.

## Acceptance Criteria

- [x] `loom.pipeline.reliability` provides import-light policy, record, and
  protocol contracts.
- [x] Runtime policy parsing and profile merging support run-level reliability
  defaults and stage-level overrides.
- [x] Unknown fields and legacy retry/timeout fields are rejected outside
  `runtime.reliability`.
- [x] Timeout remains reliability policy and is not added to `ResourceRequest`.
- [x] Package, unit, contract, integration, full PR, and suite-summary checks
  passed.

## Implementation Notes

The new `loom.pipeline.reliability` package owns plain-data models and
protocols only. Runtime integration imports those contracts to parse, serialize,
summarize, and resolve reliability policy, while later phases remain
responsible for store persistence, transaction recording, timeout diagnostics,
retry automation, and inspection.

`RunOptions`, `StageRuntimeOptions`, runtime profiles, and runtime metadata now
carry reliability policy. Stage-level policy blocks override only the selected
retry or timeout policy, so explicit disabled policies can mask inherited
defaults while omitted policies continue to inherit.

New tests implemented:

- Reliability model unit and contract round trips, strict schema validation,
  boolean constructor validation, and import-light checks.
- Runtime option/profile/metadata tests for policy parsing, serialization,
  merge semantics, legacy field rejection, and conservative defaults.
- Package import-boundary/API tests for the new reliability surface.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default suite `1782 passed, 26 skipped, 18 deselected`; config-extra `446 passed, 1819 deselected`; build succeeded |
| `make test-summary` | Passed | Overall `2256 passed, 18 skipped, 1835 deselected`; see suite table below |
| GitHub checks | Pending | To be populated by GitHub after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 102 | 0 | 0 | 1 | 0 | 103 | 30.20s | 19% |
| unit | passed | 1252 | 0 | 0 | 7 | 1 | 1259 | 77.91s | 76% |
| contract | passed | 254 | 0 | 0 | 2 | 0 | 256 | 16.81s | 58% |
| integration | passed | 159 | 0 | 0 | 8 | 13 | 167 | 72.66s | 63% |
| e2e | passed | 43 | 0 | 0 | 0 | 2 | 43 | 40.39s | 59% |
| config-extra | passed | 446 | 0 | 0 | 0 | 1819 | 446 | 90.57s | 62% |
| Overall | passed | 2256 | 0 | 0 | 18 | 1835 | 2274 | 328.53s | - |

## Risks / Follow-Ups

Phase 2 must add durable store/read-model persistence for these records.
Phases 3 through 6 still own transaction recording, timeout diagnostics, retry
automation, and read-only inspection. Stage 20 event sinks and Stage 21 cleanup
remain explicitly out of scope.
