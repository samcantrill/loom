## Summary

This phase adopts the strict authority resolver in the shared authority and
run-store factory paths. Online mutation factories now fail closed unless they
receive an explicit authority endpoint or a valid registry reference, and
endpoint-less co-located service startup is no longer hidden behind public
factory calls.

The PR also adds resolver-backed HTTP authority readiness/client construction,
rejects removed or unsupported runtime authority selections with structured
diagnostics, preserves trusted `authority_store=` injection for tests and custom
integrations, and updates tests/examples to use explicit local authority
services where mutation state crosses a process boundary.

## Acceptance Criteria

- [x] Missing or invalid online authority fails closed in central factories.
- [x] Explicit endpoint or registry references are validated before clients or
  stores are returned.
- [x] Hidden endpoint-less co-located service startup is removed from factory
  paths.
- [x] Direct database and transitional SQLite runtime selections are rejected
  with migration guidance.
- [x] Offline-first selection remains explicit and non-authoritative where no
  offline evidence store exists.
- [x] Remaining runner, worker, continuation, and SLURM migration work is
  inventoried for later phases.

## Implementation Notes

- Added `loom.pipeline.stores.authority_factory` for strict resolver-to-factory
  adaptation, registry validation, HTTP `/ready` probing, and structured
  `AuthorityFactoryError` diagnostics.
- Routed `create_run_store()` and
  `create_authority_backed_serial_run_store()` through strict authority
  resolution unless a trusted `authority_store=` is injected.
- Changed `create_service_authority_store()` so endpoint-less service configs no
  longer start hidden shared services from public factory paths.
- Preserved read-only `loom plan` behavior by avoiding mutation-store
  construction for fresh planning, while keeping resume planning on explicit
  authority.
- Kept recursive/unsupported executor validation ahead of authority
  construction for continuation and submitted-job commands.
- Updated run catalog scans to avoid hidden service startup for read-only local
  catalog inspection and to preserve missing-authority warnings for marked runs.
- Updated CLI, integration, e2e, and executable-example coverage so mutation
  tests use explicit service configs or injected stores.

New tests implemented:

- Unit and integration coverage for strict factory failure, stale registry
  rejection, HTTP readiness/client construction, offline-first unsupported
  behavior, and explicit service configs.
- Package/export coverage for new public store factory helpers.
- CLI, diagnostics, catalog, subprocess, SLURM, and executable-example coverage
  for explicit authority setup after hidden startup removal.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed with 0 errors; default harness passed with 1294 passed / 18 skipped / 14 deselected; config-extra passed with 420 passed / 1323 deselected; `uv build` succeeded. |
| `make test-summary` | Passed | `build/test-summary.md` generated at `2026-05-11T23:45:11+00:00`; overall 1740 passed / 0 failed / 0 errors / 12 skipped / 1334 deselected. |
| GitHub checks | Pending | CI will run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 69 | 0 | 0 | 1 | 0 | 70 | 10.45s |
| unit | passed | 939 | 0 | 0 | 1 | 0 | 940 | 37.24s |
| contract | passed | 146 | 0 | 0 | 2 | 0 | 148 | 9.36s |
| integration | passed | 126 | 0 | 0 | 8 | 10 | 134 | 43.22s |
| e2e | passed | 40 | 0 | 0 | 0 | 1 | 40 | 33.95s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1323 | 420 | 56.06s |
| Overall | passed | 1740 | 0 | 0 | 12 | 1334 | 1752 | 190.27s |

## Risks / Follow-Ups

- HTTP `AuthorityClient` readiness is validated here, but adapting runner
  mutation onto the HTTP client surface remains Phase 11 work.
- `PipelineRunner`, `loom run`, worker, continuation, subprocess, and SLURM
  flows still use the legacy authority-backed serial store surface and must pass
  explicit service configs when they cross process boundaries; Phases 11-13 own
  the broader runtime migration.
- Offline-first factory selection is intentionally non-mutating until the
  offline evidence writer/import flow arrives in Phase 17.
