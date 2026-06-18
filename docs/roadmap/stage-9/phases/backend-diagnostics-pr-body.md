## Summary

This phase adds read-only backend diagnostics for authoritative runs through
`loom backend inspect`, `loom backend capabilities`, and backend-neutral
helpers under `loom.diagnostics`. Users and future tools can now inspect schema
state, backend identity, revisions, lifecycle counts and stage detail,
submitted operations, cleanup and recovery records, materialized refs, and
capability diagnostics without reading private SQLite tables.

The implementation stays diagnostic-only. CLI presentation calls the
diagnostics API, the diagnostics API reads through existing backend contracts
and read-model helpers, and inspection does not mutate backend state,
materialized files, derived catalogs, leases, attempts, commits, or submitted
operations. Materialization verification is existence-only for this diagnostic
surface and does not checksum artifact payload bytes. Repair, cleanup, SQL,
export, snapshot, parallel execution, and workspace coordination remain out of
scope.

## Acceptance Criteria

- [x] `loom backend inspect` and `loom backend capabilities` are registered in
  top-level CLI help with text and JSON output.
- [x] Diagnostic results are plain-data and schema-versioned for JSON callers.
- [x] CLI modules use diagnostics helpers rather than SQLite internals.
- [x] Explicit shared-filesystem or remote requirements produce loud
  unsupported-capability diagnostics.
- [x] Tests prove backend inspection is read-only and does not load artifact
  payloads or import project stage code.

## Implementation Notes

- Added `src/loom/diagnostics/backend.py` with serializable inspection and
  capability result models, schema checks, projection revision parsing,
  materialization verification options, and capability requirement diagnostics.
- Added `src/loom/cli/backend.py` and registered `loom backend` in
  `src/loom/cli/main.py`, preserving the existing text/JSON envelope style.
- Kept the default implementation on the current local SQLite authority while
  exposing backend-neutral result records for future adapters.
- Preserved no-fallback behavior for missing or unsupported authority state and
  kept recovery and cleanup records report-only.
- Exposed backend diagnostics lazily from `loom.diagnostics` so the root
  diagnostics import remains lightweight.
- Added a read-model option that allows diagnostics to verify materialized-ref
  existence without checksum-reading payload files, while preserving checksum
  verification as the default behavior for existing read-model callers.

New tests implemented:

- Package and import-boundary tests for diagnostics exports and CLI
  presentation-only imports.
- Unit tests for diagnostic serialization, stage filtering, stale projection
  warnings, schema failures, capability requirement failures, CLI text/JSON
  output, and text-mode error detail.
- Contract coverage proving diagnostics consume `PerRunAuthorityStore`
  behavior rather than SQLite-specific internals.
- Integration coverage over SQLite-backed runs for materialization warnings,
  stale projection evidence, capability requirements, no-mutation checks, and a
  payload-read trap for backend diagnostics materialization verification.
- E2E smoke coverage for `loom backend inspect` and `loom backend
  capabilities`.

## Tests And Validation

| Check | Result | Evidence |
| --- | --- | --- |
| `make validate-pr` | Passed | Latest recorded validation after commit `b7921d7`: Ruff, Pyright, default harness, config-extra harness, and build passed. |
| `make test-summary` | Passed | Generated `build/test-summary.md` at 2026-05-09T22:02:15+00:00; overall 1501 passed, 0 failed, 0 errors, 12 skipped, and 1095 deselected. |
| GitHub checks | Pending after latest branch update | The merge manager verifies CI after the branch update is pushed. |

### Test Suite Summary

| Suite | Status | Passed | Failed | Errors | Skipped | Deselected | Total | Duration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| package | passed | 57 | 0 | 0 | 1 | 0 | 58 | 7.64s |
| unit | passed | 819 | 0 | 0 | 1 | 0 | 820 | 30.46s |
| contract | passed | 93 | 0 | 0 | 2 | 0 | 95 | 4.46s |
| integration | passed | 74 | 0 | 0 | 8 | 10 | 82 | 54.54s |
| e2e | passed | 38 | 0 | 0 | 0 | 1 | 38 | 18.27s |
| config-extra | passed | 420 | 0 | 0 | 0 | 1084 | 420 | 39.24s |
| Overall | passed | 1501 | 0 | 0 | 12 | 1095 | 1513 | 154.32s |

## Risks / Follow-Ups

- Backend diagnostics are intentionally read-only; repair, recovery mutation,
  cleanup mutation, export, import, and snapshot workflows need later explicit
  safety design.
- SQLite remains local or same-host only. Explicit shared-filesystem or remote
  requirements fail loudly until a stronger backend can prove those guarantees.
- Old v0-v8 local run directories and missing authority state do not fall back
  to legacy live-state files.
- Phase 7 and Phase 8 may reuse the capability and diagnostic model style, but
  this PR does not add parallel execution or workspace/sweep coordination.
