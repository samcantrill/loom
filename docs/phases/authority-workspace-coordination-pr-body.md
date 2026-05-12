# Summary

- Added authority protocol/client/server operations for workspace coordination: workspaces, sweeps, trial records, trial leases, non-resource counters, and coordination recovery scans.
- Added `ServiceWorkspaceCoordinationStore`, an `AuthorityClient`-backed coordination adapter, and service-owned repository coordination state.
- Kept resource leases and resource limits explicitly unsupported through structured service responses until Phase 16.

# Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed: Ruff, Pyright, default harness, config-extra harness, and build |
| `make test-summary` | Passed: package 70 passed / 1 skipped; unit 959 passed / 1 skipped; contract 151 passed / 2 skipped; integration 128 passed / 8 skipped / 10 deselected; e2e 39 passed / 2 deselected; config-extra 422 passed / 1350 deselected |

# Notes

- Service-backed coordination stores non-resource coordination facts in authority-owned state; direct client mutation of coordination SQLite paths is not introduced.
- Resource accounting remains the Phase 16 responsibility. The Phase 15 service surface returns `unsupported_capability` for resource lease and resource limit operations.
