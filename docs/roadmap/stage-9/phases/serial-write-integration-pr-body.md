## Summary

This PR integrates an internal/test-selectable SQLite-backed serial execution
write path for Phase 4 of the persistence and concurrency foundation. Public
`LocalRunStore` serial behavior stays unchanged, while tests can construct runs
whose active lifecycle, submitted-operation, attempt, lease, output commit,
artifact, and audit facts are written through backend-neutral authority
contracts.

The active-state boundary remains narrow. Local files are still materialized
evidence for configs, provenance, logs, stage inputs and fingerprints, worker
handoff documents, and payloads. Backend snapshots are the source of truth for
status, submitted operations, output commits, artifact facts, leases, and
revisions on the internal SQLite-backed path.

## Acceptance Criteria

- [x] Internal SQLite-backed serial runs mutate active state through
  `PerRunAuthorityStore`.
- [x] Public local serial execution remains on the existing file-backed default.
- [x] Controller ownership, stage attempts, stage leases, submitted operations,
  output commits, artifact facts, and audit events use backend authority on the
  selected path.
- [x] Conflicting local status, output, artifact-index, and submitted-operation
  files do not win over backend facts.
- [x] Commit failures record failed run/stage facts and do not publish active
  outputs.
- [x] SQLite-backed stage-job continuation requires backend-issued
  attempt/lease fencing facts and cannot finalize run status.

## Implementation Notes

- Added `loom.pipeline.execution.authority_adapter`, an internal
  `RunStore`-shaped adapter that pairs `LocalRunStore` materialization paths
  with `PerRunAuthorityStore` write authority.
- Routed the adapter's active reads for run/stage status, submitted operations,
  output commits, artifact facts, and stage outputs through authoritative
  snapshots instead of local live-state files.
- Replaced the SQLite-backed path's run-lock authority with backend controller
  leases, and used backend stage attempts plus fenced stage leases for output
  commits and failed-lease handling.
- Preserved local materialization for plan/config/provenance/log/stage
  fingerprint, worker handoff, and payload files.
- Added authority attempt metadata to prepared worker requests and
  internal/test-only `StageJobRunRequest` fencing fields so SQLite-backed
  stage-job continuation validates backend-issued attempt, lease, owner, and
  fencing facts before committing the target attempt.
- Prevented SQLite-backed stage-job continuation from finalizing run status;
  public local stage-job continuation keeps its existing behavior.
- Classified `AuthorityStoreError` from runner and continuation write paths as
  `store_commit`, and thawed SQLite audit-event payloads before JSON storage.

New tests implemented:

- Unit coverage for authoritative output commits and lease release, local
  conflict handling, controller-lease conflicts, submitted-operation authority,
  worker fencing metadata, missing/foreign/expired stage-job fencing,
  no-run-finalization behavior, commit-failure behavior, and legacy public
  local file-lock behavior.
- Integration coverage for SQLite-backed serial success, conflicting local
  live-state files, commit failure without active output publication, and a
  valid fenced submitted stage-job commit that leaves the run status owned by
  controller/recovery flow.

Accepted Phase 4 limitation: cleanup-candidate and attempt-failure writers are
not in the Phase 1-3 backend-neutral contracts. This phase records failed
stage/run facts and failed leases where possible; it does not add private
SQLite mutation surface for those gaps.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make validate-pr` | Passed | Ruff passed; Pyright reported 0 errors; default harness passed with 1030 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1058 deselected; source distribution and wheel built. |
| `UV_CACHE_DIR=/tmp/loom_uv_cache make test-summary` | Passed | `build/test-summary.md` generated 2026-05-09T19:24:40+00:00; overall 1475 passed, 0 failed, 0 errors, 12 skipped, 1069 deselected. |
| GitHub checks | Passed | PR #104 checks completed successfully after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 56 | 0 | 0 | 1 | 0 | 57 | 7.83s | 17% |
| unit | passed | 798 | 0 | 0 | 1 | 0 | 799 | 20.81s | 72% |
| contract | passed | 92 | 0 | 0 | 2 | 0 | 94 | 4.43s | 49% |
| integration | passed | 72 | 0 | 0 | 8 | 10 | 80 | 52.95s | 55% |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 37 | 15.49s | 67% |
| config-extra | passed | 420 | 0 | 0 | 0 | 1058 | 420 | 35.20s | 74% |
| Overall | passed | 1475 | 0 | 0 | 12 | 1069 | 1487 | 136.70s | - |

## Risks / Follow-Ups

- Phase 5 still owns the public SQLite-first default plus broader planning,
  resume, status, catalog, and artifact-summary read-path conversion.
- Cleanup-candidate writes and attempt-specific failure writes need a future
  backend-neutral contract extension if they must become first-class authority
  facts.
- Public CLI worker-owned backend continuation remains future work; this phase
  keeps the backend-fenced stage-job path internal/test-selected and does not
  add public CLI fencing flags.
