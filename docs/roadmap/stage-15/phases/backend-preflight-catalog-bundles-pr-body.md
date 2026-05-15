# External Artifact Interface - Phase 4: Backend Preflight and Metadata Preservation

## Summary

- Added explicit artifact-backend preflight targets plus registry, handler, and
  capability checks under the artifacts preflight group.
- Kept backend checks cheap and explicit: no plugin discovery, no network or
  credential probes, no lookup/publish/materialization, and required operations
  fail closed when support is missing, unknown, or unsupported.
- Added run metadata projection helpers for Stage 15 artifact summaries and
  tests proving catalog and bundle metadata preserve external/published
  summaries.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/unit/loom/diagnostics tests/unit/loom/runs tests/contracts` | 330 passed / 2 skipped |
| `make validate-pr` | passed |
| `make test-summary` | passed: overall 2117 passed / 18 skipped / 1702 deselected |

## Scope Notes

- Generic Stage 14 plugin metadata/list/load checks still do not satisfy Stage
  15 backend readiness.
- This phase preserves Stage 15 summaries in existing metadata surfaces; Stage
  12 exchange schema decisions remain in Phase 5.
- Payload movement, materialization, retention cleanup, real backend adapters,
  network checks, and credential checks remain out of scope.
