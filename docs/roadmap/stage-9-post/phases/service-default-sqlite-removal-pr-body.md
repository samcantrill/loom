## Summary

- Makes co-located service authority the default runtime backend and rejects stale `transitional_sqlite` runtime configuration with explicit removal diagnostics.
- Routes default execution, public run-store creation, diagnostics, backend CLI behavior, and run-catalog scans away from run-local SQLite authority while preserving derived catalog SQLite sidecars.
- Keeps private SQLite authority implementation coverage for backend-specific regression tests, but removes it from supported runtime conformance matrices.
- Documents service/database authority as the supported runtime path and clarifies that retained SQLite sidecars are non-authoritative projections.

## Tests

| Command | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default suite, config-extra suite, and `uv build` |
| `make test-summary` | Passed: package 57, unit 859, contract 110, integration 101, e2e 39, config-extra 420 |

## Assumptions And Risks

- The local default authority is a shared stdlib co-located service process; hosted service operations, auth, tenancy, and persistence remain out of scope.
- `transitional_sqlite` remains recognizable only so stale env or serialized config can fail clearly.
- Catalog SQLite remains a rebuildable projection sidecar, not active lifecycle authority.
