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
  `PerRunAuthorityStore.snapshot()` only when schema policy says authoritative
  facts are readable. Warning-only unsupported-schema reads now return
  machine-readable `UNSUPPORTED_SCHEMA` warnings without exposing SQLite
  internals; strict reads raise `MaterializationReadModelError` carrying those
  warnings. The read path does not read private SQLite tables, legacy
  `status.json` or artifact-index files, project code, CLI modules, or
  artifact payload contents as state truth.
- Materialized payload, log, config, provenance, and worker handoff files are
  represented as refs with diagnostics. Missing or corrupt refs become warnings,
  or strict read failures when explicitly requested, without changing lifecycle
  facts from the authoritative backend.
- The store package exports the new read helpers deliberately, with package
  tests covering the exact export list and import-light boundary.
- Blocker-resolution pass 1/3 addressed the automated review findings for
  unsupported-schema warning-only reads, `PARTIAL_COMMIT` coverage, cleanup
  candidate carry-through, and refreshed validation evidence.

New tests implemented:

- Unit coverage for derived payload refs, strict warning rejection, corrupt and
  missing materialized refs, local ref classification, completed-run bundle
  metadata, schema and stale-projection warnings, unsupported-schema
  warning-only reads, `PARTIAL_COMMIT` warnings, cleanup candidate
  carry-through, and legacy status-file non-authority.
- Contract coverage over in-memory and SQLite authority stores for backend
  facts, submitted operations, materialized refs, missing-ref warnings, and
  corrupt-ref warnings.
- Integration coverage for SQLite-backed materialization diagnostics, completed
  bundle metadata ignoring legacy files, unsupported-schema warning-only reads,
  and active-run revision-change warnings.
- Package coverage for the new public store exports and import boundaries.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Ruff, Pyright, default harness (1019 passed, 17 skipped, 14 deselected), config-extra harness (416 passed, 1047 deselected), and `uv build` passed. |
| `make test-summary` | Passed | Generated `build/test-summary.md` at 2026-05-09T17:39:49+00:00; overall 1460 passed, 0 failed, 0 errors, 11 skipped, 1058 deselected. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration | Coverage |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| package | passed | 56 | 0 | 0 | 1 | 0 | 57 | 7.93s | 17% |
| unit | passed | 787 | 0 | 0 | 1 | 0 | 788 | 16.81s | 71% |
| contract | passed | 92 | 0 | 0 | 2 | 0 | 94 | 4.42s | 50% |
| integration | passed | 72 | 0 | 0 | 7 | 10 | 79 | 52.60s | 56% |
| e2e | passed | 37 | 0 | 0 | 0 | 1 | 37 | 15.55s | 68% |
| config-extra | passed | 416 | 0 | 0 | 0 | 1047 | 416 | 32.04s | 70% |
| Overall | passed | 1460 | 0 | 0 | 11 | 1058 | 1471 | 129.35s | - |

## Risks / Follow-Ups

- The read model is now an internal compatibility surface for later v9 phases
  and v10 bundle planning; public export semantics still belong to future work.
- Active-run revision warnings are intentionally conservative and may be refined
  when Phase 5 public reads or Phase 7 parallel execution need stronger
  consistency guarantees.
- Remote materialization states remain future work; this phase focuses on local
  filesystem refs without making payload presence authoritative.
