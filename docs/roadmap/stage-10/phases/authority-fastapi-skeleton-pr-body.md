## Summary

- Added FastAPI as the explicit runtime service dependency and `httpx` as dev-only support for deterministic in-process TestClient coverage.
- Introduced the lightweight `loom.authority` package with a FastAPI app factory, injected service facts, operational health/live/ready/version/capability routes, and a non-mutating `/v1/authority` route-group boundary for future mutation APIs.
- Returned protocol-compatible readiness, version, and capability payloads using the Phase 2 authority protocol and capability value objects while keeping FastAPI imports out of core runtime modules.
- Added package import-boundary, unit, contract, and integration coverage for app construction, route ownership, dependency overrides, response shapes, and TestClient execution.

## Tests

| Command | Result |
| --- | --- |
| `UV_CACHE_DIR=/tmp/uv-cache make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and build |
| `UV_CACHE_DIR=/tmp/uv-cache make test-summary` | Passed: suite summary written to `build/test-summary.md` |

| Suite | Result |
| --- | --- |
| package | 64 passed, 1 skipped |
| unit | 890 passed, 1 skipped |
| contract | 131 passed, 2 skipped |
| integration | 102 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1229 deselected |
| overall | 1646 passed, 12 skipped, 1240 deselected |

## Assumptions And Risks

- Phase 3 only creates the app and route skeleton; repository-backed readiness, durable mutation routes, client transport behavior, supervisor commands, registry writes, and runtime adoption remain in later phases.
- FastAPI response-model generation is disabled on these stub routes so the transport returns plain protocol dictionaries rather than making Pydantic schemas the protocol authority.
- Default skeleton capabilities are intentionally conservative and empty until later repository and mutation phases provide real service facts.
- TestClient and existing local manager-backed tests require execution outside the sandbox because sandboxed runs hang or block local socket creation.
