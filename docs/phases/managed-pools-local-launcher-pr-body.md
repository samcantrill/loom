## Summary

Adds Phase 7 managed local dispatch on top of the queue service surface from
Phase 6. The queue now has read-only managed-pool resource reconciliation
against authority limits, non-terminal dispatch/controller status seams, and a
local adapter that acquires authority resource leases, starts local process
groups, observes completion, releases leases, and cancels active local work.

The implementation stays local-only. SLURM/SSH adapters, queue-owned resource
limit mutation, retries, and CLI/supervisor wrappers remain out of scope.

## Acceptance Criteria

- [x] Local queued work can run through a managed local adapter with authority
  resource admission and lease release.
- [x] Managed queue pools validate configured resource expectations against
  authority without mutating authority limits.
- [x] Launch-contract drift is detected before resource admission or process
  start.
- [x] Pending queue cancellation remains queue-local, and active local
  cancellation terminates the local process group and releases leases.
- [x] Foreground/controller reconciliation does not silently exit while managed
  local work is active; lost active handles become explicit unknown/recovery
  states.

## Implementation Notes

- Added `loom.queue.resources` with managed-pool reconciliation/report helpers
  over the Phase 3 resource admission readback seam.
- Added `loom.queue.local` with `LocalQueueDispatchAdapter`,
  `SubprocessLocalProcessRunner`, process-group metadata, drift checks,
  resource admission, lease release, status observation, and cancellation.
- Extended `QueueDispatchResult` and `QueueController` for active
  non-terminal dispatch, adapter status inspection, adapter cancellation, and
  claimed/dispatched recovery reconciliation.
- Added `QueueService.read_item()` and `QueueService.recovery_items()` for
  controller/status read models.
- Added `loom.queue.status` for queue/adapter/authority evidence joins for
  active managed work.
- Preserved the lightweight `loom.queue` root and added import-boundary
  coverage for local/resource modules.

New tests cover:

- Managed-pool success/mismatch/missing-limit reconciliation without mutation.
- Local adapter launch, status, cancellation, drift mismatch, admission
  rejection, and recovery-needed states.
- Controller active-dispatch completion and cancellation paths.
- Managed local integration with SQLite queue state plus in-memory authority
  coordination.
- Contract shape for managed-pool reconciliation reports and package import
  boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 7 suite | Passed | 54 passed |
| `uv run ruff check ...` | Passed | Queue/source/test targets clean |
| `uv run pyright ...` | Passed | 0 errors, 0 warnings |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall 1882 passed, 12 skipped, 1463 deselected |
| GitHub checks | Pending | Will be verified after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 74 | 0 | 0 | 1 | 0 | 12.07s |
| unit | passed | 1023 | 0 | 0 | 1 | 1 | 50.86s |
| contract | passed | 165 | 0 | 0 | 2 | 0 | 10.95s |
| integration | passed | 144 | 0 | 0 | 8 | 11 | 51.38s |
| e2e | passed | 40 | 0 | 0 | 0 | 2 | 36.24s |
| config-extra | passed | 436 | 0 | 0 | 0 | 1449 | 77.89s |

## Risks / Follow-Ups

- Local recovery after controller restart records explicit unknown/recovery
  state rather than reattaching to arbitrary existing process groups.
- The initial local launch contract is command/argv-shaped; Phase 9 can wrap it
  in friendlier operational config.
- Delegated SLURM dispatch remains Phase 8 scope.
