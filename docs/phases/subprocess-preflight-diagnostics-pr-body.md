## Summary

Implements Phase 4 of v5 by adding selected-subprocess preflight diagnostics
and concise subprocess failure UX. `loom preflight` and the minimal pre-run
preflight now add subprocess-specific Python executable and worker-command
availability checks only when `subprocess` is the selected executor, keeping
local preflight output stable.

`loom run` failure summaries now include optional attempt, executor, exit code,
signal, failure record, stdout, stderr, and traceback paths. Text output stays
compact, and JSON output exposes the same facts through `failure_summary`.

## Acceptance Criteria

- [x] Selected subprocess preflight reports structured failures for missing
  Python executable or worker command availability.
- [x] Missing subprocess worker/Python availability is distinct from generic
  unknown-executor rejection.
- [x] Preflight checks do not launch user stage code.
- [x] CLI run output remains concise while pointing to persisted failure,
  stdout, stderr, and traceback paths.
- [x] JSON output carries the new failure-summary fields through existing
  output conventions.
- [x] Existing status/log/artifact inspection paths continue to read persisted
  subprocess failure metadata.

## Implementation Notes

- Added stable executor check IDs: `executor.subprocess.python` and
  `executor.subprocess.worker`.
- Gated subprocess availability checks on selected executor
  `runtime_options.executor == "subprocess"`.
- Checked the current Python executable with deterministic path/executable
  resolution and checked worker command availability through
  `importlib.util.find_spec("loom.cli.main")`.
- Extended run failure summaries and text formatting with optional
  process/log/failure fields while preserving existing fields.
- Updated focused preflight, CLI, and execution docs for current subprocess
  diagnostics behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright with config extra, default harness, config-extra harness, and build all passed. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 50 | 0 | 0 | 1 | 0 | 5.21s |
| unit | passed | 593 | 0 | 0 | 1 | 0 | 6.41s |
| contract | passed | 55 | 0 | 0 | 2 | 0 | 2.03s |
| integration | passed | 20 | 0 | 0 | 7 | 7 | 2.90s |
| e2e | passed | 18 | 0 | 0 | 0 | 0 | 7.62s |
| config-extra | passed | 401 | 0 | 0 | 0 | 736 | 16.74s |

## Risks / Follow-Ups

- Worker command availability is import-resolution based and intentionally does
  not execute a dummy worker command.
- Failure record paths are best-effort local run-store hints; remote stores and
  attempt archive directories remain deferred.
- Phase 5 still owns broader examples, final contract hardening, and deferred
  behavior documentation.
