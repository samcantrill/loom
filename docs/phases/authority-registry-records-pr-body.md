## Summary

Implements Phase 8 by adding deterministic workspace-local authority registry
records under `.loom/authority/`. The new store helper can write and read
versioned workspace and allocation-scoped JSON records, redact sensitive
metadata recursively, validate stale or incompatible records as distinct
fail-closed outcomes, and convert valid or rejected records into existing
authority resolver facts.

Supervisor lifecycle commands, runtime resolver/factory adoption, user-global
discovery, DB mutation, and offline import remain out of scope for later v10
phases.

## Acceptance Criteria

- [x] Registry records can be written atomically and read from
  `.loom/authority/current.json`.
- [x] Allocation-scoped records use deterministic validated paths under
  `.loom/authority/allocations/`.
- [x] Persisted references and diagnostics redact sensitive metadata while
  rejecting endpoints with userinfo or sensitive query parameters.
- [x] Missing, malformed, expired, wrong-workspace, generation-mismatched,
  version-incompatible, unavailable, and unhealthy records produce distinct
  fail-closed validation statuses.
- [x] Registry validation maps to existing resolver hints, service-health facts,
  diagnostics, and failure kinds without runtime adoption.

## Implementation Notes

- Added `loom.pipeline.stores.authority_registry` with record models, schema
  versioning, path helpers, atomic write/read helpers, validation helpers, and
  resolver conversion helpers.
- Exported the registry surface through `loom.pipeline.stores` and updated
  public API/package boundary expectations.
- Added unit coverage for serialization, redaction, endpoint safety, path
  validation, validation statuses, and incompatible protocol versions.
- Added contract coverage for resolver failure mapping and integration coverage
  for temp workspace registry writes and missing-record validation.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff passed; Pyright passed; default pytest passed with 1268 passed, 18 skipped, 14 deselected; config-extra passed with 420 passed, 1297 deselected; build succeeded. |
| `make test-summary` | Passed | Overall 1714 passed, 12 skipped, 1308 deselected. |
| GitHub checks | Pending | To run after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Skipped | Deselected | Duration |
| --- | --- | ---: | ---: | ---: | ---: |
| package | passed | 67 | 1 | 0 | 14.28s |
| unit | passed | 919 | 1 | 0 | 45.41s |
| contract | passed | 145 | 2 | 0 | 15.21s |
| integration | passed | 124 | 8 | 10 | 64.87s |
| e2e | passed | 39 | 0 | 1 | 35.66s |
| config-extra | passed | 420 | 0 | 1297 | 64.39s |

## Risks / Follow-Ups

- Phase 9 must write these records from supervisor lifecycle commands and keep
  health/generation facts current.
- Phase 10 must decide how strict resolver/factory adoption handles stale
  records without hidden service startup.
- Registry health is recorded, not actively polled in this phase.
