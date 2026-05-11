## Summary

This PR adds run-level durable state to the private authority service repository. The repository schema advances to version 2 and now stores cross-run revisions, run records, controller leases, submitted operations, audit events, cleanup candidates, and recovery records.

The new behavior stays below the service API boundary. It does not add FastAPI mutation routes, stage lifecycle tables, attempts, output commits, artifact facts, runtime caller adoption, or public repository exports.

## Acceptance Criteria

- [x] Repository tests can admit a run, transition it through valid run states, reject stale status/revision mutations, and read back run snapshots.
- [x] Controller lease facts are persisted, fenced, renewed, released, and rejected on stale owner/fencing data.
- [x] Revisions advance monotonically and stale expected revisions prevent mutation.
- [x] Submitted operations, audit events, cleanup candidates, and recovery records are durable and queryable.
- [x] Behavior remains private to `loom.authority._repository` with no public direct-DB mutation path.

## Implementation Notes

- Extended `src/loom/authority/_repository.py` with schema version 2 tables for run lifecycle state, repository revisions, controller leases, submitted operations, cleanup candidates, recovery records, and audit events.
- Added private methods for run admission, run snapshots, status transitions, controller lease lifecycle, submitted-operation read/write/list, audit append/list, cleanup candidate record/list, recovery record/list, and recovery scanning.
- Reused existing backend-neutral value models such as `BackendRevision`, `StatusTransition`, `LeaseRecord`, `AuthoritativeRunSnapshot`, `SubmittedOperationRecord`, `PipelineEventRecord`, `CleanupCandidate`, and `RecoveryRecord`.
- Preserved Phase 5 scope by leaving stage lifecycle, attempts, output commits, artifact facts, HTTP mapping, and runtime adoption for later phases.

New tests implemented:

- Unit tests for schema version 2, run admission, duplicate rejection, transition preconditions, stale expected revisions, and controller lease fencing.
- Contract tests showing stale revision and stale fencing repository failures map cleanly to existing protocol rejection categories.
- Integration tests for file-backed lifecycle persistence across handles, submitted operations, audit events, cleanup/recovery records, lease expiry recovery, and transaction rollback.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright passed; default pytest passed with 1227 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1256 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Overall 1673 passed, 12 skipped, 1267 deselected. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 65 | 0 | 0 | 1 | 0 | 66 | 14.00s |
| unit | passed | 899 | 0 | 0 | 1 | 0 | 900 | 47.27s |
| contract | passed | 137 | 0 | 0 | 2 | 0 | 139 | 14.74s |
| integration | passed | 113 | 0 | 0 | 8 | 10 | 121 | 173.88s |
| e2e | passed | 39 | 0 | 0 | 0 | 1 | 39 | 60.90s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1256 | 420 | 85.42s |
| Overall | passed | 1673 | 0 | 0 | 12 | 1267 | 1685 | 396.21s |

## Risks / Follow-Ups

- Stage lifecycle, attempts, output commits, artifact facts, and stage leases are intentionally deferred to Phase 6.
- FastAPI protocol mapping and HTTP status behavior are intentionally deferred to Phase 7.
- Version 1 private repositories are rejected rather than migrated because no released service repository schema exists yet.
