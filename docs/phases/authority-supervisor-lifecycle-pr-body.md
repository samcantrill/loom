## Summary

Implements Phase 9 by adding explicit local authority supervisor lifecycle
commands: `loom authority start`, `status`, `doctor`, `stop`, and `restart`.
The new authority-owned supervisor helpers initialize a repository-backed
FastAPI service, wait for readiness, write workspace-local registry records,
inspect process/repository/readiness/registry/generation state, stop the local
process, and rotate service generation on restart.

Runtime resolver/factory adoption, hidden supervisor startup, workspace
coordination, resource admission, user-global discovery, and offline import
remain out of scope for later v10 phases.

## Acceptance Criteria

- [x] Users can explicitly start, inspect, stop, and restart a local authority
  supervisor.
- [x] `start` and `restart` require an explicit `--state-dir`; no workspace-local
  default service state directory was added.
- [x] Successful start initializes the private authority repository, verifies
  FastAPI readiness, records endpoint/state-dir/workspace/generation facts, and
  writes the Phase 8 registry artifact.
- [x] Status and doctor results distinguish process state, readiness, repository
  compatibility, registry validation, and generation match.
- [x] Restart rotates service generation and republishes registry facts.
- [x] Ordinary runtime mutation paths remain unchanged and do not start hidden
  supervisors.

## Implementation Notes

- Added `loom.authority.supervisor` for local PID/state-file management,
  repository identity checks, readiness polling, registry publication, stop,
  restart, and result models.
- Added private `loom.authority._server` as the repository-backed FastAPI process
  entrypoint.
- Registered `loom authority` in the CLI with lazy supervisor imports and
  text/JSON result formatting.
- Added `uvicorn>=0.30,<1` as the bounded ASGI server dependency required to run
  the existing FastAPI authority app.
- Added package, unit, contract, integration, and e2e coverage for import
  boundaries, command behavior, readiness/registry compatibility, real local
  process lifecycle, and CLI smoke flow.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default pytest passed with 1284 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1313 deselected; build succeeded. |
| `make test-summary` | Passed | Overall 1730 passed, 12 skipped, 1324 deselected. |
| GitHub checks | Pending | To run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: |
| package | passed | 68 | 1 | 0 | 14.63s |
| unit | passed | 930 | 1 | 0 | 45.95s |
| contract | passed | 146 | 2 | 0 | 15.13s |
| integration | passed | 126 | 8 | 10 | 65.32s |
| e2e | passed | 40 | 0 | 1 | 37.53s |
| config-extra | passed | 420 | 0 | 1313 | 64.46s |

## Risks / Follow-Ups

- Phase 10 still needs strict resolver/factory adoption of the registry records
  written here.
- The local supervisor is PID-file based and single-host; hosted process manager
  support remains future work.
- The new ASGI dependency is limited to serving the local FastAPI authority app.
