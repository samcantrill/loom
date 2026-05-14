## Summary

This PR adds stage-level durable state to the private authority service repository. The repository schema advances to version 3 and now stores cross-run stage records, attempts, stage leases, output commits, and artifact facts.

The new behavior remains private to the service repository. It does not add FastAPI mutation routes, client transport mapping, runtime caller migration, registry/supervisor behavior, resource admission, or offline import.

## Acceptance Criteria

- [x] Repository tests cover stage transition ordering, attempt allocation, output commit, artifact fact persistence, and submitted-operation compatibility.
- [x] Stage leases are persisted, fenced, renewed, released, and rejected on stale owner/fencing data or expiry.
- [x] Stale expected revisions and stale service generations prevent stage output or terminal-attempt writes.
- [x] Run snapshots include durable stage attempts, active leases, latest commits, and artifact facts.
- [x] No runtime caller uses the private repository directly.

## Implementation Notes

- Extended `src/loom/authority/_repository.py` with schema version 3 tables for stage state, attempts, stage leases, output commits, and artifact facts.
- Added private methods for stage transition, attempt allocation, stage lease lifecycle, terminal attempt recording, and fenced output commits.
- Reused existing backend-neutral value models such as `StageAttempt`, `StageLifecycleSnapshot`, `LeaseRecord`, `OutputCommitRecord`, `ArtifactFactRecord`, and `OutputCommit`.
- Preserved Phase 6 scope by leaving FastAPI route mapping, runtime migration, registry/supervisor behavior, resource admission, and offline evidence manifests for later phases.

New tests implemented:

- Unit tests for schema version 3, stage transition preconditions, attempt allocation, stage lease renewal/release, stale generation rejection, output commit persistence, and terminal attempt state.
- Contract tests for stage output commit read-model compatibility and stale generation mapping to existing protocol rejection categories.
- Integration tests for file-backed output commit/artifact persistence across handles, expired stage lease recovery and retry, and transaction rollback around stage writes.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed | Ruff passed; Pyright passed; default pytest passed with 1237 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1266 deselected; build succeeded. |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed | Overall 1683 passed, 12 skipped, 1277 deselected. |
| GitHub checks | Pending | To be run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 65 | 0 | 0 | 1 | 0 | 66 | 23.69s |
| unit | passed | 904 | 0 | 0 | 1 | 0 | 905 | 109.21s |
| contract | passed | 139 | 0 | 0 | 2 | 0 | 141 | 22.85s |
| integration | passed | 116 | 0 | 0 | 8 | 10 | 124 | 106.31s |
| e2e | passed | 39 | 0 | 0 | 0 | 1 | 39 | 36.57s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1266 | 420 | 66.35s |
| Overall | passed | 1683 | 0 | 0 | 12 | 1277 | 1695 | 364.99s |

## Risks / Follow-Ups

- FastAPI protocol mapping and client behavior are intentionally deferred to Phase 7.
- Runtime runner/worker/SLURM adoption remains deferred to later phases.
- Version 2 private repositories are rejected rather than migrated because no released service repository schema exists yet.
