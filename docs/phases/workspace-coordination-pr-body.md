## Summary

This phase adds the cross-run workspace/sweep coordination foundation for v9
without turning sweeps into executable workflows. It extends the
`WorkspaceCoordinationStore` contract with fenced lease renewal/failure and
guarded counter operations, then adds a private local SQLite coordination
backend for workspace identity, sweep identity, trial references, trial leases,
resource leases, resource limits, counters, revisions, and recovery scans.

The new SQLite backend is deliberately separate from the run-local SQLite
authority backend. Trial records reference ordinary `run_uri` values and do not
open or copy per-run lifecycle state, stage attempts, commits, artifact facts,
submitted operations, or catalog projections. Its capabilities declare
cross-run coordination and global counters for local or same-host use only, with
loud diagnostics for shared-filesystem or remote assumptions.

## Acceptance Criteria

- [x] Workspace/sweep coordination stores cross-run facts only.
- [x] Per-run stage lifecycle remains owned by each run's authoritative backend.
- [x] Trial and resource leases are claimable, renewable, releasable,
  fail-able, expirable, and recoverable through the coordination contract.
- [x] Local SQLite coordination declares local/same-host safety only and exposes
  machine-readable diagnostics for unsafe shared-filesystem or remote
  assumptions.
- [x] Resource limits and counters are guarded by backend state and recover
  expired resource-lease capacity where the backend can prove expiry.
- [x] Coordination records reference ordinary `run_uri` values rather than
  copying run state.
- [x] Documentation keeps v11 sequential sweep manifests compatible and defers
  full sweep execution, scheduler policy, and distributed controllers.

## Implementation Notes

- Added `SQLiteWorkspaceCoordinationStore` under `loom.pipeline.stores` as a
  private-schema, stdlib-only SQLite implementation of the workspace
  coordination contract.
- Tightened `WorkspaceCoordinationStore` with `renew_lease`, `fail_lease`,
  `set_resource_limit`, `set_counter_limit`, and `decrement_counter` so both
  fake and SQLite stores expose the same lease/counter behavior.
- Added `coordination_requirement_diagnostics(...)` for local coordination
  assumption checks using the existing capability diagnostic vocabulary.
- Updated the in-memory conformance store to match SQLite semantics for
  duplicate identity failures, fenced lease mutation, resource limits, counters,
  and recovery scans.
- Documented the local/same-host SQLite coordination boundary in run-store,
  sweep, and source-tree docs.

New tests implemented:

- Package/API import coverage for the tightened coordination protocol and
  diagnostic helper.
- Unit coverage for SQLite coordination schema policy and capability limits.
- Contract coverage parametrized across fake and SQLite stores for cross-run
  facts, duplicate/unknown identity failures, lease fencing, recovery,
  resource limits, counters, and diagnostics.
- Integration coverage for concurrent trial claims, resource limit recovery,
  transactional counter limits, and trial `run_uri` references that do not read
  per-run authority state.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness (`1088 passed, 18 skipped, 14 deselected`), config-extra harness (`420 passed, 1117 deselected`), and `uv build` succeeded. |
| `make test-summary` | Passed | `build/test-summary.md` generated at `2026-05-10T00:04:44+00:00`; overall `1534 passed`, `0 failed`, `0 errors`, `12 skipped`, `1128 deselected`. |
| GitHub checks | Pending | CI will run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 57 | 0 | 0 | 1 | 0 | 58 | 7.69s |
| unit | passed | 830 | 0 | 0 | 1 | 0 | 831 | 30.26s |
| contract | passed | 101 | 0 | 0 | 2 | 0 | 103 | 5.06s |
| integration | passed | 87 | 0 | 0 | 8 | 10 | 95 | 61.03s |
| e2e | passed | 39 | 0 | 0 | 0 | 1 | 39 | 19.00s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1117 | 420 | 39.41s |
| Overall | passed | 1534 | 0 | 0 | 12 | 1128 | 1546 | 162.45s |

## Risks / Follow-Ups

- SQLite workspace coordination is local or same-host only; remote,
  multi-host, service-backed, or scheduler-backed coordination remains future
  work.
- This phase provides the coordination foundation only. Full sweep planning,
  sweep execution, fairness, adaptive algorithms, retry policy, and result
  collection remain out of scope.
- Counter recovery is intentionally limited to capacity tied to active resource
  leases and guarded counter state; richer quota/fairness accounting belongs
  with concrete sweep or scheduler behavior.
