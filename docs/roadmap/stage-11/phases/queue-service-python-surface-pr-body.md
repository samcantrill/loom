## Summary

Adds the Phase 6 Python-first queue control surface on top of the Phase 5 queue
records and SQLite repository. The new surface includes normalized queue
service specs, explicit queue YAML loading, lazy config-extra composition
normalization, an in-process queue service boundary, a transport-neutral client,
and Python controller entrypoints for fake daemon-style dispatch and foreground
drain.

The implementation keeps real local/SLURM launch behavior, managed resources,
CLI wrappers, and authority mutation out of scope. Queue control modules remain
dependency-light and do not import private authority storage.

## Acceptance Criteria

- [x] Queue can be configured, started, and controlled from Python against fake
  work.
- [x] Foreground-drain compatibility mode works against fake work without
  orphaning locally managed claims.
- [x] Queue code does not import or touch private authority repository modules.

## Implementation Notes

- Added `QueueServiceSpec` and `QueueControllerSpec` normalization, plus
  `load_queue_spec`, `compose_queue_spec`, and
  `queue_spec_from_composed_config`.
- Added `QueueService`, `QueueClient`, `QueueEnqueueRequest`,
  `QueueItemInspection`, and lifecycle/status records over the existing queue
  repository protocol.
- Added `QueueController`, `FakeQueueDispatchAdapter`, and foreground-drain
  result records. The controller records dispatch handles before completing
  fake work and leaves no recovery records after successful fake drain.
- Kept config composition imports lazy and added package-boundary coverage for
  queue control modules.

New tests implemented:

- Package/import-boundary tests for the expanded `loom.queue` API.
- Unit tests for config normalization, service/client behavior, and fake
  controller behavior.
- Contract tests for queue config and Python API shapes.
- Integration tests for service restart recovery and fake foreground drain from
  loaded queue config.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `uv run pytest ... Phase 6 targets` | Passed | 56 passed, 2 skipped |
| `uv run --extra config pytest ... queue loader targets` | Passed | 5 passed |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall 1868 passed, 12 skipped, 1449 deselected |
| GitHub checks | Pending | Will be verified after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 73 | 0 | 0 | 1 | 0 | 12.00s |
| unit | passed | 1013 | 0 | 0 | 1 | 1 | 50.31s |
| contract | passed | 164 | 0 | 0 | 2 | 0 | 11.06s |
| integration | passed | 142 | 0 | 0 | 8 | 11 | 52.15s |
| e2e | passed | 40 | 0 | 0 | 0 | 2 | 36.92s |
| config-extra | passed | 436 | 0 | 0 | 0 | 1435 | 79.13s |

## Risks / Follow-Ups

- The service boundary is in-process only; Phase 9 owns operational CLI and
  supervisor wrapping.
- Queue topology is explicit service configuration rather than durable admin
  state.
- Fake dispatch is synchronous by design; Phase 7 and Phase 8 own real local
  and delegated adapter behavior.
