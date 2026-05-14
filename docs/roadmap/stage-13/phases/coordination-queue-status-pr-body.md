## Summary

Implements Phase 4 of deterministic sweeps: coordination projection, queue
submission, and read-only sweep status aggregation.

Planned sweeps can now project `SweepIdentity` and `TrialReference` facts into
an available `WorkspaceCoordinationStore`, submit finite planned trials as
whole-run queue items through `QueueService`, and build aggregate status
summaries from manifests plus supplied run, queue, and coordination read
models. Queue dispatch remains submit-only and does not drain or control the
queue.

## Acceptance Criteria

- [x] Coordination helpers record sweep and trial references in in-memory and
  SQLite coordination stores.
- [x] Queue dispatch builds one whole-run enqueue request per planned trial with
  stable queue item IDs and sweep/trial metadata.
- [x] Queue dispatch returns submission results and continues after per-trial
  enqueue failures.
- [x] Sweep status aggregation derives pending, queued, running, succeeded,
  failed, cancelled, and early-stopped trial summaries from supplied read
  models.
- [x] Queue and sweep ownership boundaries stay separate; queue dispatch does
  not drain, poll, cancel, or complete queue items.

## Implementation Notes

- Added `loom.pipeline.sweep.coordination` for optional coordination projection
  and run/queue status to `TrialState` mapping.
- Added queue-backed sweep dispatch records and `enqueue_sweep_trials(...)`.
- Added `loom.pipeline.sweep.status` for read-only status summaries and
  early-stop derivation from structured run metadata.
- Extended direct dispatch with optional coordination updates.
- Updated `QueueService.enqueue` to thaw nested structured request fields before
  durable queue records are built, allowing structured whole-run trial intents.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| Targeted Phase 4 tests | Passed | 42 passed across sweep unit, sweep contract, sweep integration, package, import-boundary, and focused queue tests |
| Broader queue/coordination tests | Passed | 74 passed across queue unit/integration/contracts and workspace coordination contract |
| `uv run --extra config pyright` | Passed | 0 errors |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Wrote `build/test-summary.md` |
| GitHub checks | Pending | Available after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| package | passed | 79 | 0 | 0 | 1 | 0 |
| unit | passed | 1083 | 0 | 0 | 7 | 1 |
| contract | passed | 197 | 0 | 0 | 2 | 0 |
| integration | passed | 154 | 0 | 0 | 8 | 13 |
| e2e | passed | 42 | 0 | 0 | 0 | 2 |
| config-extra | passed | 438 | 0 | 0 | 0 | 1564 |

## Risks / Follow-Ups

- Phase 5 owns the public `loom sweep` CLI, user docs, and collection commands.
- Queue dispatch intentionally submits queue items only; controller loops,
  cancellation, retry, and scheduler-specific policy remain outside Phase 4.
- Collection and extraction remain deferred to Phase 5 and later roadmap work.
