## Summary

This PR adds the backend-neutral authoritative read and materialization boundary
for v9 Phase 3. Later status, catalog, diagnostics, and bundle inputs can now
consume one read model over `PerRunAuthorityStore` snapshots instead of querying
private SQLite tables or treating materialized files as active state truth.

It also adds payload-free completed-run bundle metadata, local materialized-ref
classification, and machine-readable warnings for schema mismatches, stale
projections, partial commits, active revision changes, and missing or corrupt
materialized refs.

## Implementation Notes

- Added `loom.pipeline.stores.materialization_read_models` with
  `read_authoritative_run`, `read_completed_run_bundle_metadata`, strict versus
  warning-only read options, local materialization requests, and checksum-aware
  materialized-ref diagnostics.
- The read path consumes `PerRunAuthorityStore.check_schema()` and
  `PerRunAuthorityStore.snapshot()` only. It does not read private SQLite
  tables, legacy `status.json` or artifact-index files, project code, CLI
  modules, or artifact payload contents as state truth.
- Materialized payload, log, config, provenance, and worker handoff files are
  represented as refs with diagnostics. Missing or corrupt refs become warnings,
  or strict read failures when explicitly requested, without changing lifecycle
  facts from the authoritative backend.
- The store package exports the new read helpers deliberately, with package
  tests covering the exact export list and import-light boundary.

New tests implemented:

- Unit coverage for derived payload refs, strict warning rejection, corrupt and
  missing materialized refs, local ref classification, completed-run bundle
  metadata, schema and stale-projection warnings, and legacy status-file
  non-authority.
- Contract coverage over in-memory and SQLite authority stores for backend
  facts, submitted operations, materialized refs, missing-ref warnings, and
  corrupt-ref warnings.
- Integration coverage for SQLite-backed materialization diagnostics, completed
  bundle metadata ignoring legacy files, and active-run revision-change
  warnings.
- Package coverage for the new public store exports and import boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness (1016 passed, 17 skipped, 14 deselected), config-extra harness (416 passed, 1044 deselected), and `uv build` passed. |
| `make test-summary` | Passed | Generated `build/test-summary.md` at 2026-05-09T17:09:40+00:00; overall 1457 passed, 0 failed, 0 errors, 11 skipped, 1055 deselected. |
| GitHub checks | Pending | Starts after PR creation. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 56 | 0 | 0 | 1 | 0 | 57 | 7.65s | 17% |
| unit | passed | 785 | 0 | 0 | 1 | 0 | 786 | 16.80s | 71% |
| contract | passed | 92 | 0 | 0 | 2 | 0 | 94 | 4.56s | 50% |
| integration | passed | 71 | 0 | 0 | 7 | 10 | 78 | 52.81s | 56% |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 37 | 15.53s | 68% |
| config-extra | passed | 416 | 0 | 0 | 0 | 1044 | 416 | 32.37s | 70% |
| Overall | passed | 1457 | 0 | 0 | 11 | 1055 | 1468 | 129.71s | - |

## Risks / Follow-Ups

- The read model is now an internal compatibility surface for later v9 phases
  and v10 bundle planning; public export semantics still belong to future work.
- Active-run revision warnings are intentionally conservative and may be refined
  when Phase 5 public reads or Phase 7 parallel execution need stronger
  consistency guarantees.
- Remote materialization states remain future work; this phase focuses on local
  filesystem refs without making payload presence authoritative.
