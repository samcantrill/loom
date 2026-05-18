## Summary

@samcantrill

This PR adds Stage 22 Phase 3 representative end-to-end evidence for public example journeys. It introduces `tests/e2e/test_example_journeys.py` covering local run/resume, authority lifecycle CLI, SLURM dry-run artifacts, and Docker executor success plus failure diagnostics, then points the selected manifests and docs at those named validation paths.

The phase remains docs/examples/tests-only. No `src/loom` runtime modules, public APIs, CLI behavior, real external-system validation, or new runtime dependencies are changed.

## Acceptance Criteria

- [x] Representative CLI/Python example journeys have named e2e validation paths.
- [x] The selected journeys use local/fake-backed validation and temporary roots.
- [x] Manual live Docker/SLURM boundaries remain manual.
- [x] Final PR-gate validation and suite summary passed.

## Implementation Notes

| Area | Notes |
| --- | --- |
| Target/base | `codex/examples-e2e-workflows` targeting `develop` |
| Stack | Root phase PR; stack predecessor: none |
| E2E coverage | Added representative example journey tests for local resume, authority lifecycle, SLURM dry-runs, and Docker success/failure diagnostics. |
| Example hardening | Updated the local execution example to use a local SQLite authority store and `StageContext.load_input`, keeping the example runnable without a socket-backed authority service. |
| Documentation | Added representative e2e evidence entries to execution/operations READMEs and focused authority/container/SLURM coverage docs. |
| Runtime scope | No `src/loom` changes and no new runtime dependencies. |

New tests implemented:

| Test path | Behavior validated |
| --- | --- |
| `tests/e2e/test_example_journeys.py::test_e2e_example_local_pipeline_run_with_resume` | Local example composes config, runs, resumes the same run, reuses stages, and persists a run URI. |
| `tests/e2e/test_example_journeys.py::test_e2e_example_authority_lifecycle_cli` | Authority lifecycle example reports ready status, valid registry state, doctor result, restart generation change, and stopped state. |
| `tests/e2e/test_example_journeys.py::test_e2e_example_slurm_dry_run_basics` | SLURM dry-run example produces single-job and afterok manifests/scripts without scheduler IDs and with expected warning codes. |
| `tests/e2e/test_example_journeys.py::test_e2e_example_docker_executor_smoke_and_failure_diagnostics` | Docker example exercises fake-Docker success and failure diagnostics without a real Docker daemon. |

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed `1963 passed, 26 skipped, 30 deselected`; config-extra passed `460 passed, 3 skipped, 2001 deselected`; `uv build` succeeded. |
| `make test-summary` | Passed | Wrote `build/test-summary.md` with overall `2452 passed, 21 skipped, 2026 deselected`. |
| Targeted Phase 3 e2e | Passed | `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/e2e/test_example_journeys.py -q`: `4 passed`. |
| Docs/example integration | Passed | `UV_CACHE_DIR=/tmp/uv-cache uv run --extra config pytest tests/integration/docs/test_v0_python_examples.py tests/integration/examples/test_example_workflows.py -q`: `40 passed`. |
| E2E gate | Passed | `make test-e2e`: `46 passed, 6 deselected`. |
| GitHub checks | Pending after PR open | Final merge gate will use the GitHub check result for this branch. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 108 | 0 | 0 | 1 | 0 | 109 | 19.81s | 18% |
| unit | passed | 1394 | 0 | 0 | 7 | 1 | 1401 | 78.14s | 77% |
| contract | passed | 274 | 0 | 0 | 2 | 0 | 276 | 15.12s | 56% |
| integration | passed | 170 | 0 | 0 | 8 | 18 | 178 | 68.87s | 62% |
| e2e | passed | 46 | 0 | 0 | 0 | 6 | 46 | 46.43s | 59% |
| config-extra | passed | 460 | 0 | 0 | 3 | 2001 | 463 | 135.87s | 60% |
| Overall | passed | 2452 | 0 | 0 | 21 | 2026 | 2473 | 364.24s | - |

## Risks / Follow-Ups

| Item | Notes |
| --- | --- |
| Representative coverage | E2E coverage intentionally stays representative rather than per-example exhaustive. |
| Optional dependency placement | The new example journey e2e module is marked `optional_dependency` so it runs in config-extra with the config dependencies it needs. |
| External systems | Docker and SLURM evidence remains fake/local or dry-run; live daemon and cluster validation remains manual. |
| Later-stage scope | Phase 4 still owns final docs audit, final completion metadata, and final evidence rollup. |
