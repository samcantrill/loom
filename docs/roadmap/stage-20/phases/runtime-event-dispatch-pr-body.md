## Summary

Phase 3 wires runtime lifecycle event emission through an explicit dispatch
helper so configured event sinks observe events only after the backing runtime
fact has been committed. Durable dispatch still appends `PipelineEventRecord`
values to the run event store first, then invokes the supplied registry with a
narrow sink context for observer links and callback failure facts.

The phase also adds an explicit non-durable dispatch mode for sink-enabled runs.
That path skips durable event append, dispatches an `EventReference` with
`durability="non_durable"` and an in-process `dispatch_sequence`, records
callback failures best-effort when possible, and returns warning metadata on the
run result.

## Acceptance Criteria

- [x] Runtime dispatch preserves committed fact, event append/projection, then
  sink dispatch ordering for run and stage lifecycle events.
- [x] Explicit sink registries can be supplied without plugin loading or global
  registration.
- [x] Callback failures are recorded best-effort through Phase 2 observer-fact
  stores and do not change run correctness.
- [x] Explicit non-durable dispatch uses non-durable event identity without
  fabricating durable store sequences.

## Implementation Notes

- Added `RuntimeEventDispatcher` and `EventDispatchWarning` in
  `loom.pipeline.execution.eventing`, plus an execution-local sink context that
  can only record observer links and callback failures for the triggering event.
- Extended `RunRequest` with `event_sink_registry` and `event_persistence`.
  Non-durable persistence requires a non-empty registry.
- Routed runner and lifecycle event emissions through the dispatcher while
  leaving the no-registry path on the existing append-only event behavior.
- Stage 19-specific retry, timeout, transaction, and submission event names
  remain deferred rather than inventing reliability event semantics in this PR.

New tests cover durable dispatch ordering, observer-link writeback, callback
failure persistence, non-durable identity, request validation, and local runner
behavior with configured sinks.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `uv run pytest tests/unit/loom/pipeline/execution/test_eventing.py tests/unit/loom/pipeline/execution/test_runner.py tests/unit/loom/pipeline/execution/test_lifecycle.py tests/unit/loom/pipeline/execution/test_execution_models.py tests/unit/loom/pipeline/test_event_sinks.py` | Passed | 68 passed |
| `uv run pytest tests/integration/pipeline/test_local_execution.py tests/integration/pipeline/test_local_execution_resume.py tests/integration/pipeline/test_local_execution_failures.py tests/integration/pipeline/test_local_stores.py` | Passed | 1 passed, 3 optional-dependency modules skipped in the plain dev environment |
| `uv run --extra config pytest tests/unit/loom/diagnostics tests/integration/diagnostics` | Passed | 100 passed |
| `make validate-pr` | Passed | Ruff, Pyright, default harness, config-extra harness, and build passed |
| `make test-summary` | Passed | Overall passed; 2381 passed, 21 skipped, 1957 deselected |
| GitHub checks | Pending | To run after PR creation |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected |
| --- | --- | ---: | ---: | ---: |
| package | passed | 105 | 1 | 0 |
| unit | passed | 1355 | 7 | 1 |
| contract | passed | 263 | 2 | 0 |
| integration | passed | 165 | 8 | 13 |
| e2e | passed | 44 | 0 | 2 |
| config-extra | passed | 449 | 3 | 1941 |

## Risks / Follow-Ups

- Reliability-specific Stage 19 event names remain a follow-up; this phase keeps
  lifecycle event dispatch ordered after committed facts and records the
  deferral explicitly.
- Phase 4 still owns explicit plugin loading, diagnostics or CLI presentation,
  and broader inspection documentation.
