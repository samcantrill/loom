## Summary

This PR implements Phase 7 by adding an opt-in service-backed authority backend
behind the public `create_run_store()` factory path.

The backend is a deterministic stdlib local service for contract and
integration coverage. Clients connect through an endpoint/authkey configuration
and cannot use a direct shared authority state path. The transitional SQLite
authority backend remains the default.

## Changes

- Added `LocalAuthorityService`, `ServiceAuthorityStore`, and
  `create_service_authority_store()` for service-bound run and stage authority.
- Routed `co_located_service`, `managed_service`, and
  `allocation_scoped_service` authority configs through the service client in
  `create_run_store()`.
- Implemented run admission, run/stage transitions, attempts, leases, fencing,
  submitted operations, output commits, artifact facts, snapshots, recovery
  scans, cleanup candidates, audit events, monotonic revisions, and backend
  clock state behind the service boundary.
- Added honest capability records for supported single-host service semantics
  and explicit unsupported production multi-host, shared-filesystem,
  deferred-finalization, cross-run, and global-counter claims.
- Added conformance, factory, diagnostics, service lifecycle, unavailable
  service, direct-path rejection, and concurrent client coverage.

## Tests

| Suite | Result |
| --- | --- |
| `make validate-pr` | Passed Ruff, Pyright, default tests, config-extra tests, and build |
| package | 57 passed, 1 skipped |
| unit | 843 passed, 1 skipped |
| contract | 110 passed, 2 skipped |
| integration | 95 passed, 8 skipped, 10 deselected |
| e2e | 39 passed, 1 deselected |
| config-extra | 420 passed, 1147 deselected |

Targeted service backend coverage passed:
`uv run --extra config pytest tests/unit/loom/pipeline/stores/test_service_authority.py tests/integration/pipeline/test_authority_factory.py tests/integration/pipeline/test_service_authority_backend.py tests/integration/pipeline/test_backend_diagnostics.py tests/contracts/test_run_store_authority_contract.py -q`.

An initial `make test-summary` run hit a transient failure in an unrelated
parallel-execution integration test; that test passed in isolation and the final
`make test-summary` run passed.

## Assumptions And Risks

- The new backend proves service endpoint and transaction semantics for a local
  deterministic service fixture; it does not claim hosted production durability,
  tenancy, high availability, arbitrary multi-host authority, or deferred
  finalization.
- Service helper types are concrete module APIs under
  `loom.pipeline.stores.service_authority`; the stable public construction path
  is still `create_run_store()` with an `AuthorityConfig`.
