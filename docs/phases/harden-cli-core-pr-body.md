## Summary

Completes Phase 6 of CLI Core by hardening the shipped v2 command surface with end-to-end coverage through `main(argv)` and updating user-facing docs for `loom validate`, `loom plan`, and `loom run`.

The docs now describe the supported v2 behavior, strict local `file://` run URI forms, the `--check-targets` consent boundary, plan/dry-run read-only behavior, JSON envelopes, and the command families deferred beyond v2.

## Acceptance Criteria

- [x] README documents the supported v2 validate/plan/run quickstart.
- [x] CLI feature docs mark validate/plan/run as the current surface and defer later command families.
- [x] Strict local run URI forms and rejected forms are documented.
- [x] `validate --check-targets` is documented as the constructor consent boundary.
- [x] E2E tests cover validate, `--check-targets`, plan, run, failed run, dry-run, resume, explicit run URI, default run URI, and JSON output through `main(argv)`.
- [x] CLI import boundaries remain covered.

## Implementation Notes

- Added `tests/e2e/test_cli_core.py` with workflow-level coverage over the already implemented v2 commands.
- Updated `README.md` with CLI examples and corrected the Python API quickstart to pass the composed config object into `RunRequest`.
- Updated `docs/features/cli.md` so current v2 support and deferred roadmap commands are explicit.
- No new CLI options, command modules, runtime behavior, store behavior, or dependencies were added.

New tests validate successful and failing CLI workflows, target-constructor warnings, default and explicit run URI behavior, dry-run non-mutation, strict resume reuse, unsupported executor errors, and plain-path run URI rejection.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness 505 passed / 12 skipped; config-extra 380 passed / 519 deselected; build succeeded. |
| `make test-summary` | Passed | Suite summary below. |
| GitHub checks | Pending | To be updated after PR CI completes. |

### Test Suite Summary

| Suite | Result | Evidence |
| --- | --- | --- |
| package | Passed | 43 passed / 1 skipped |
| unit | Passed | 417 passed / 1 skipped |
| contract | Passed | 36 passed / 2 skipped |
| integration | Passed | 9 passed / 5 skipped |
| e2e | Passed | 14 passed |
| config-extra | Passed | 380 passed / 519 deselected |

## Risks / Follow-Ups

- Later CLI phases still need status/logs/artifacts/stage-worker behavior and non-local executors.
- V2 remains local-only; remote stores and non-local run URI schemes are intentionally rejected.
