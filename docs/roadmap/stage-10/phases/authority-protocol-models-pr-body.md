## Summary

- Added transport-independent authority protocol value models for readiness, version/schema compatibility, request metadata, accepted results, structured rejections, and response envelopes.
- Exposed the intentional protocol surface through `loom.pipeline.stores` without importing FastAPI, Pydantic, SQLite, service-authority, or private repository modules.
- Added unit and contract coverage for plain-data round trips, unknown-field rejection, version compatibility, operation/error vocabularies, fenced acknowledgements, snapshots, readiness, stale-generation errors, and unsupported-capability errors.
- Serialized local event appends to resolve a GitHub CI blocker where parallel stage execution could assign duplicate event sequence numbers.
- Made atomic write temp paths high-entropy to avoid same-target temp-file collisions under parallel run-store writes.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and build |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed: suite summary written to `build/test-summary.md` |

| Suite | Result |
| --- | --- |
| package | 62 passed, 1 skipped |
| unit | 887 passed, 1 skipped |
| contract | 127 passed, 2 skipped |
| integration | 101 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1219 deselected |
| overall | 1636 passed, 12 skipped, 1230 deselected |

## Assumptions And Risks

- Phase 2 defines value objects only; FastAPI routes, transport dispatch, repository bindings, client behavior, supervisor lifecycle, and runtime adoption remain in later phases.
- Protocol envelopes intentionally nest existing public read-model records only where they already represent stable domain-neutral facts.
- Operation grouping stays at representative authority families rather than mirroring every store method as a public wire record.
- Automated review found and blocker resolution fixed readiness parsing for conflicting top-level and nested compatibility facts.
- GitHub CI exposed a pre-existing local event append race under parallel stage execution; blocker resolution fixed it with an in-process append lock and unit coverage.
- A later CI run exposed same-target atomic temp-path collisions; blocker resolution fixed temp allocation without changing artifact or store document shapes.
