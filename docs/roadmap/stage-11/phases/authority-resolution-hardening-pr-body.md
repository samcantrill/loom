## Summary

Implements v11 Phase 1 authority/supervisor hardening. Supervisor lifecycle
commands now support an explicit workspace-default state directory via
`--use-workspace-default`, resolving to `<workspace-root>/.loom/authority/service`,
while preserving the existing explicit `--state-dir` path.

The supervisor now rejects starting a second live, ready authority for the same
workspace from a different state directory. The guard treats registry records as
bootstrap hints by confirming the referenced supervisor state, process, and
readiness before failing closed. This phase also fixes validation blockers in
invalid offline-manifest CLI error classification and offline-import replay
event assertions so the full PR gate remains meaningful.

## Acceptance Criteria

- [x] Mutating authority selection continues to fail closed on stale or missing live authority evidence.
- [x] Supervisor commands expose a consistent explicit workspace-default state-directory surface.
- [x] Restart generation changes remain observable and stale-generation coverage remains intact.
- [x] Starting a second live authority for the same workspace is rejected.

## Implementation Notes

- Added `workspace_default_supervisor_state_dir(...)` and
  `AUTHORITY_SUPERVISOR_WORKSPACE_DEFAULT_DIR`.
- Added `use_workspace_default` helper parameters and CLI
  `--use-workspace-default` wiring for `start`, `status`, `doctor`, `stop`, and
  `restart`.
- Kept startup explicit: `--state-dir` and `--use-workspace-default` are
  mutually exclusive, and one of them is required for `start` and `restart`.
- Added a live duplicate-authority guard that checks registry, state file,
  process liveness, and `/ready` before rejecting.
- Wrapped invalid offline evidence manifest parsing/validation as
  `OfflineEvidenceError` so the existing CLI config-error contract is upheld.

New tests implemented:

- Unit coverage for workspace-default path resolution, state-dir conflicts, and
  duplicate live authority rejection.
- Integration coverage for a real supervisor lifecycle using the explicit
  workspace-default state directory.
- E2E CLI smoke now exercises `--use-workspace-default`.
- Focused validation-blocker tests for invalid offline manifest classification
  and replay-event comparison.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default harness passed; config-extra harness passed; build passed |
| `make test-summary` | Passed | Wrote `build/test-summary.md` |
| GitHub checks | Pending | To be run after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 70 | 0 | 0 | 1 | 0 | 71 | 11.46s |
| unit | passed | 989 | 0 | 0 | 1 | 0 | 990 | 48.51s |
| contract | passed | 157 | 0 | 0 | 2 | 0 | 159 | 10.65s |
| integration | passed | 131 | 0 | 0 | 8 | 10 | 139 | 49.93s |
| e2e | passed | 40 | 0 | 0 | 0 | 2 | 40 | 36.00s |
| config-extra | passed | 434 | 0 | 0 | 0 | 1390 | 434 | 76.44s |
| Overall | passed | 1821 | 0 | 0 | 12 | 1402 | 1833 | 232.99s |

## Risks / Follow-Ups

- Workspace-default behavior is explicit-only in this phase; no implicit
  supervisor start default is introduced.
- Main queue work must still wait for the remaining `v10-post` prerequisite
  phases and transition checkpoint before Phase 5.
