## Summary

- Added transport-independent authority protocol value models for readiness, version/schema compatibility, request metadata, accepted results, structured rejections, and response envelopes.
- Exposed the intentional protocol surface through `loom.pipeline.stores` without importing FastAPI, Pydantic, SQLite, service-authority, or private repository modules.
- Added unit and contract coverage for plain-data round trips, unknown-field rejection, version compatibility, operation/error vocabularies, fenced acknowledgements, snapshots, readiness, stale-generation errors, and unsupported-capability errors.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and build |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed: suite summary written to `build/test-summary.md` |

| Suite | Result |
| --- | --- |
| package | 62 passed, 1 skipped |
| unit | 884 passed, 1 skipped |
| contract | 127 passed, 2 skipped |
| integration | 101 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1216 deselected |
| overall | 1633 passed, 12 skipped, 1227 deselected |

## Assumptions And Risks

- Phase 2 defines value objects only; FastAPI routes, transport dispatch, repository bindings, client behavior, supervisor lifecycle, and runtime adoption remain in later phases.
- Protocol envelopes intentionally nest existing public read-model records only where they already represent stable domain-neutral facts.
- Operation grouping stays at representative authority families rather than mirroring every store method as a public wire record.
