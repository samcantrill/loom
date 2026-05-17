# Runtime Events - Phase 2: Sink Registry and Observer Facts

## Summary

- Adds import-light `loom.pipeline.event_sinks` contracts: explicit
  instance-local registry, observe-only context protocols, dispatch result
  records, callback failure facts, and observer-link facts.
- Adds store/read facets for event sink failures and observer links, with local
  JSONL sidecars, SQLite authority persistence, service authority persistence,
  authority-adapter forwarding, and fake authority support.
- Keeps observer facts separate from ordinary runtime events: they do not write
  `events.jsonl`, do not become `PipelineEventRecord` audit events, and do not
  expose broad store/runtime mutation handles to sinks.
- Documents observer fact sidecars in feature and structure docs.

## Tests

| Command | Result |
| --- | --- |
| `uv run pytest tests/package/test_pipeline_store_api.py tests/package/test_import_boundaries.py tests/unit/loom/pipeline/test_event_sinks.py` | Passed, 72 tests |
| `uv run pytest tests/contracts/test_store_contract.py tests/contracts/test_authority_store_contract.py tests/unit/loom/pipeline/stores tests/integration/pipeline/test_local_stores.py` | Passed, 225 tests |
| `make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, build |
| `make test-summary` | Passed: package 105 passed/1 skipped; unit 1350 passed/7 skipped/1 deselected; contract 263 passed/2 skipped; integration 165 passed/8 skipped/13 deselected; e2e 44 passed/2 deselected; config-extra 447 passed/3 skipped/1936 deselected |

## Scope Notes

- Runtime dispatch wiring remains Phase 3 scope.
- Plugin entry point loading, diagnostics/CLI presentation, and final docs
  remain Phase 4 scope.
- Callback failures are best-effort observer facts and do not change run
  correctness in this phase.
