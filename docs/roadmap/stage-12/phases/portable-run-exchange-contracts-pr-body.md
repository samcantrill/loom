## Summary

@samcantrill

This PR starts Stage 12 by adding the portable-run exchange contract surface: adapter-neutral source/target identity records, local bundle manifest records, shared diagnostics, import/export/inspection result envelopes, migration-readiness blockers, transfer evidence placeholders, and minimal `RunExporter`/`RunImporter` protocols.

It also carries the confirmed Stage 12 planning and implementation-plan artifacts so the Phase 1 branch contains the durable workflow source used for the implementation.

## Acceptance Criteria

- [x] Public portable-run and bundle manifest records round-trip through plain data.
- [x] Local bundle manifest parsing rejects unsupported versions and unknown top-level fields while preserving explicit `extensions`.
- [x] Minimal importer/exporter protocols are structural and usable by fake adapters without plugin discovery or provider clients.
- [x] `loom.runs` public exports remain lightweight and do not pull CLI, execution, store, queue controller, or optional config dependencies into import paths.
- [x] Archive I/O, import behavior, CLI commands, external providers, transfer handlers, and live migrated resume remain out of scope.

## Implementation Notes

The new contracts live in `src/loom/runs/models.py` and are exported from `loom.runs`. They deliberately stay as plain dataclasses, enums, and protocols over `PlainData` mappings so authority/offline evidence and later adapters can depend on the result shapes without importing archive helpers or catalog scanning behavior.

The manifest contract is strict at the top level and reserves future opaque data for explicit `extensions` fields. Export and payload-selection defaults are metadata-only; payload/log/workspace inclusion remains explicit for later phases. Deferred import behaviors such as preserve-source identity, overwrite/reuse collision handling, and non-strict checksum policy are not exposed as accepted public policy values.

New tests implemented:

- Contract tests for manifest round-trips, strict unknown-field rejection, result envelopes, and structural fake importer/exporter conformance.
- Unit tests for manifest strictness, schema-version rejection, metadata-only defaults, deferred-policy rejection, and readiness record round-trips.
- Package tests updated for intentional `loom.runs` exports and existing import-boundary coverage.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default suite, config-extra suite, and build passed outside the sandbox. |
| `make test-summary` | Passed | Wrote `build/test-summary.md`; all suites passed. |
| GitHub checks | Pending | To be populated after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 77 | 0 | 0 | 1 | 0 | 78 | 16.52s |
| unit | passed | 1038 | 0 | 0 | 7 | 1 | 1045 | 59.28s |
| contract | passed | 171 | 0 | 0 | 2 | 0 | 173 | 12.04s |
| integration | passed | 145 | 0 | 0 | 8 | 13 | 153 | 54.28s |
| e2e | passed | 41 | 0 | 0 | 0 | 2 | 41 | 38.56s |
| config-extra | passed | 438 | 0 | 0 | 0 | 1481 | 438 | 84.68s |
| Overall | passed | 1910 | 0 | 0 | 18 | 1497 | 1928 | 265.36s |

## Risks / Follow-Ups

- Phase 2 must implement archive export/inspect behavior against these contracts without widening the adapter protocol shape.
- Phase 3 must align offline evidence and bundle import semantics without making offline evidence a local bundle format.
- Provider discovery, concrete transfer handlers, and live migrated resume remain deferred.
