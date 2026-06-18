## Summary

@samcantrill

This PR hardens Stage 22 Phase 2 integration evidence for the runnable `full` operations examples. It adds focused integration coverage for captured logs, failing-run diagnostics, resource preflight warnings, resource lease coordination, and offline import rejection behavior, then points the affected example manifests and docs at those named validation paths.

The phase remains examples/docs/tests-only: no runtime modules, public APIs, CLI behavior, external-system defaults, or e2e journeys are changed.

## Acceptance Criteria

- [x] `full` operations examples have named integration validation paths.
- [x] Example documentation records the concrete evidence paths for the newly covered workflows.
- [x] Validation evidence is local/fake-backed and isolated through temporary output/run roots.
- [x] Final PR-gate validation and suite summary were recorded.

## Implementation Notes

| Area | Notes |
| --- | --- |
| Target/base | `codex/examples-integration-coverage` targeting `develop` |
| Stack | Root phase PR; stack predecessor: none |
| Example metadata | Updated five operations manifests from docs-only validation references to exact integration test paths. |
| Documentation | Added operations README evidence mapping and a focused authority coverage evidence table for authority-backed examples. |
| Runtime scope | No `src/loom` changes and no new runtime dependencies. |

New tests implemented:

| Test path | Behavior validated |
| --- | --- |
| `tests/integration/examples/test_example_workflows.py::test_example_captured_logs_records_captured_output` | Captured-log example records successful run state, stdout tail, stderr path availability, and a persisted run URI. |
| `tests/integration/examples/test_example_workflows.py::test_example_failing_run_reports_diagnostics_summary` | Failing-run example reports preflight pass, failed run state, failed stage summary, and no artifacts. |
| `tests/integration/examples/test_example_workflows.py::test_example_resource_preflight_reports_resource_warnings_and_strict_exit` | Resource-preflight example reports warning statuses and `resource.ignored` diagnostics. |
| `tests/integration/examples/test_example_workflows.py::test_example_resource_leases_coordinate_blocked_then_released_state` | Resource-lease example proves blocked, released, and reacquired lease states. |
| `tests/integration/examples/test_example_workflows.py::test_example_offline_import_rejections_report_rejection_codes_and_acceptance` | Offline-import example reports distinct rejection codes and a non-failed accepted import. |

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed `1963 passed, 26 skipped, 21 deselected`; config-extra passed `456 passed, 3 skipped, 2001 deselected`; `uv build` succeeded. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with overall `2448 passed, 21 skipped, 2022 deselected`. |
| Targeted docs/example checks | Passed | `40 passed in 56.42s` for `tests/integration/docs/test_v0_python_examples.py` and `tests/integration/examples/test_example_workflows.py` with config extras. |
| Integration gate | Passed | `make test-integration`: `170 passed, 89 deselected`. |
| GitHub checks | Pending after PR open | PR #197 targets `develop`; final merge gate will use the GitHub check result for this branch. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 108 | 0 | 0 | 1 | 0 | 109 | 20.32s | 18% |
| unit | passed | 1394 | 0 | 0 | 7 | 1 | 1401 | 79.07s | 77% |
| contract | passed | 274 | 0 | 0 | 2 | 0 | 276 | 15.12s | 56% |
| integration | passed | 170 | 0 | 0 | 8 | 18 | 178 | 69.71s | 62% |
| e2e | passed | 46 | 0 | 0 | 0 | 2 | 46 | 46.13s | 59% |
| config-extra | passed | 456 | 0 | 0 | 3 | 2001 | 459 | 124.02s | 60% |
| Overall | passed | 2448 | 0 | 0 | 21 | 2022 | 2469 | 354.36s | - |

## Risks / Follow-Ups

| Item | Notes |
| --- | --- |
| Full examples remain outside the fastest smoke path | Accepted to keep smoke validation fast while still adding named integration evidence. |
| Assertions focus on stable summaries | Avoids brittle golden-output tests; revisit if user-visible drift escapes this coverage. |
| External systems remain manual | Real Docker, Apptainer, SLURM, network, and provider-backed checks remain outside default validation. |
| Later-stage scope | Phase 3 still owns representative e2e workflows; Phase 4 still owns final docs audit and completion metadata. |
