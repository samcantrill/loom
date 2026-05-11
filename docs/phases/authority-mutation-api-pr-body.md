## Summary

Implements Phase 7 by wiring the private authority repository into the FastAPI
mutation boundary and adding a repository-free `AuthorityClient` transport
adapter. The new service path accepts protocol envelopes, returns structured
acknowledgements or rejections, and keeps SQLite/private repository details
inside `loom.authority`.

Runtime caller migration, workspace registry records, supervisor lifecycle,
coordination, resource admission, and offline import remain out of scope for
later v10 phases.

## Acceptance Criteria

- [x] Repository-backed FastAPI routes can perform representative run and stage
  lifecycle mutations through protocol envelopes.
- [x] Client behavior stays repository-free and maps timeout, unavailable
  service, and invalid response cases into structured protocol rejections.
- [x] Repository conflicts, stale revisions, stale generation, stale fencing,
  unsupported mutation services, and validation failures return protocol
  rejection envelopes rather than raw framework tracebacks.
- [x] Default app construction remains non-mutating unless a mutation service is
  configured.
- [x] Existing runtime callers remain unchanged.

## Implementation Notes

- Added `loom.authority.mutation_service.AuthorityMutationService` to adapt
  protocol requests into private repository calls.
- Expanded `/v1/authority` FastAPI routes for run admission/snapshot/
  transition, controller leases, submitted operations, stage transitions,
  attempt allocation, stage leases, terminal attempts, and output commits.
- Added `loom.pipeline.stores.AuthorityClient` using stdlib HTTP with an
  injectable transport for deterministic in-process tests.
- Added repository-backed service capability facts while preserving the default
  skeleton app as unsupported for mutations.

New tests cover client transport behavior, repository-backed service wiring,
route-level protocol envelopes, public export expectations, import boundaries,
in-process mutation flows, stale generation, stale fencing, conflict, and
validation rejection behavior.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default pytest passed with 1248 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1277 deselected; build succeeded. |
| `make test-summary` | Passed | Overall 1694 passed, 12 skipped, 1288 deselected. |
| GitHub checks | Pending | To run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: |
| package | passed | 66 | 1 | 0 | 14.56s |
| unit | passed | 908 | 1 | 0 | 46.49s |
| contract | passed | 141 | 2 | 0 | 15.45s |
| integration | passed | 120 | 8 | 10 | 65.24s |
| e2e | passed | 39 | 0 | 1 | 35.79s |
| config-extra | passed | 420 | 0 | 1277 | 63.70s |

## Risks / Follow-Ups

- Route endpoints currently use the generic protocol envelope shape; later API
  documentation can add narrower DTOs if needed.
- Error classification depends on current private repository error messages.
- Phase 8+ still need registry, supervisor, strict resolver adoption, runtime
  migration, coordination, resources, and offline import work.
